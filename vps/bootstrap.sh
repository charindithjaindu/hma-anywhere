#!/usr/bin/env bash
# bootstrap.sh — fresh VM -> HMA tunnel + local proxies + systemd, in one run.
#
#   git clone <repo> && cd hma-suite/vps
#   sudo ./bootstrap.sh --countries US,GB --code XXXXX-XXXXX-XXXXX --wallet-key XXXXXX-XXXXXX-XXXXXX
#
# What it does:
#   1. installs openvpn/dante/tinyproxy/curl
#   2. SSH-survival routing (setup-netrules.sh)
#   3. license: redeem --code if this machine can (HMA installed), else verify
#      via --wallet-key, else instruct the official one-time redemption
#   4. proxies: setup-proxy.sh --http 8888 (auto-generated password if none)
#   5. tunnel: first --countries entry via select-country.sh
#   6. systemd watchdog: auto-restarts the tunnel if it dies
#
# You still do ONE manual thing: copy the per-country .ovpn files from your
# HMA account into /etc/openvpn/hma/<CC>.conf (dashboard auth-gated, by design).
# The script waits for at least one and tells you exactly what to do.
set -euo pipefail

COUNTRIES="" CODE="" WALLET_KEY="" PROXY_PASS="" USER_NAME="danteproxy" HTTP_PORT="8888" NO_WATCHDOG=0
while [ $# -gt 0 ]; do
  case "$1" in
    --countries) COUNTRIES="$2"; shift 2 ;;
    --code)      CODE="$2"; shift 2 ;;
    --wallet-key) WALLET_KEY="$2"; shift 2 ;;
    --proxy-pass) PROXY_PASS="$2"; shift 2 ;;
    --proxy-user) USER_NAME="$2"; shift 2 ;;
    --http-port) HTTP_PORT="$2"; shift 2 ;;
    --no-watchdog) NO_WATCHDOG=1; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
HERE=$(cd "$(dirname "$0")" && pwd)
SUITEROOT=$(dirname "$HERE")

step() { printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }

# ------------------------------------------------------------- 1. packages
step "installing packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq openvpn tinyproxy curl python3 >/dev/null

# ------------------------------------------------------------- 2. netrules
step "SSH-survival routing"
"$HERE/setup-netrules.sh"

# ------------------------------------------------------------- 3. license
step "license / activation"
ACC="$SUITEROOT/bin/hma_account.py"
ACTIVATED=no
if [ -n "$CODE" ]; then
  if python3 "$ACC" activate --code "$CODE" ${WALLET_KEY:+--wallet-key "$WALLET_KEY"}; then
    ACTIVATED=yes
  else
    echo "NOTE: code redemption needs HMA installed (protobuf codec) — redeem ONCE at"
    echo "      https://my.hma.com (Account -> redeem code) or on your Mac:"
    echo "        python3 bin/hma_account.py activate --code $CODE"
    echo "      ...then re-run bootstrap with --wallet-key to verify. Continuing."
  fi
fi
if [ "$ACTIVATED" = no ] && [ -n "$WALLET_KEY" ]; then
  echo "verifying license with wallet key (raw HTTP):"
  python3 "$ACC" licenses --wallet-key "$WALLET_KEY" || {
    echo "WARNING: license query failed — check the wallet key / connectivity." >&2
  }
fi
if [ "$ACTIVATED" = no ] && [ -z "$WALLET_KEY" ]; then
  cat <<'EOF'
No activation/verification performed. The tunnel below uses your HMA account
credentials (auth-user-pass) regardless; the license check is informational.
EOF
fi

# ------------------------------------------------------------- 4. configs
step "per-country OpenVPN configs"
CONF_DIR=/etc/openvpn/hma
mkdir -p "$CONF_DIR"
FOUND=no
for f in "$CONF_DIR"/*.conf; do [ -e "$f" ] && FOUND=yes && break; done
if [ "$FOUND" = no ]; then
  cat <<EOF
ACTION REQUIRED: copy the per-location .ovpn files from your HMA account
(dashboard -> manual setup / router configs) into:

    $CONF_DIR/US.conf   $CONF_DIR/GB.conf   ...   (rename to <CC>.conf)

Then re-run this script (it is resume-safe). Nothing else was changed yet
beyond packages + routing rules.
EOF
  exit 3
fi
[ -f "$CONF_DIR/hma.creds" ] || {
  echo "NOTE: $CONF_DIR/hma.creds missing — create it with your HMA account login:"
  echo "  sudo sh -c 'printf \"HMA_LOGIN\\nHMA_PASSWORD\\n\" > $CONF_DIR/hma.creds && chmod 600 $CONF_DIR/hma.creds'"
  read -rs -p "or enter HMA login now (user): " HMA_USER || true
  if [ -n "${HMA_USER:-}" ]; then
    read -rs -p "password: " HMA_PASS; echo
    printf '%s\n%s\n' "$HMA_USER" "$HMA_PASS" > "$CONF_DIR/hma.creds"
    chmod 600 "$CONF_DIR/hma.creds"
  fi
}

# ------------------------------------------------------------- 5. proxies
step "proxies (SOCKS5 :1080 + HTTP :$HTTP_PORT)"
if [ -z "$PROXY_PASS" ]; then PROXY_PASS=$(head -c 16 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 16); fi
"$HERE/setup-proxy.sh" --user "$USER_NAME" --password "$PROXY_PASS" --http "$HTTP_PORT"

# ------------------------------------------------------------- 6. tunnel
FIRST="${COUNTRIES%%,*}"; FIRST=$(echo "${FIRST:-US}" | tr '[:lower:]' '[:upper:]')
step "tunnel up: $FIRST"
"$HERE/select-country.sh" "$FIRST"
"$HERE/check-egress.sh" || echo "(egress check inconclusive — verify manually)"

# ------------------------------------------------------------- 7. watchdog
step "systemd watchdog"
if [ "$NO_WATCHDOG" = 0 ]; then
  install -m 755 /dev/stdin /usr/local/sbin/hma-watchdog <<'EOF'
#!/usr/bin/env bash
# restart the HMA tunnel if it died; log to syslog
UNIT=openvpn-client@hma.service
if ! systemctl is-active --quiet "$UNIT"; then
  logger -t hma-watchdog "tunnel down — restarting"
  systemctl restart "$UNIT"
  sleep 5
  systemctl is-active --quiet "$UNIT" && logger -t hma-watchdog "tunnel recovered" \
                                            || logger -t hma-watchdog "tunnel STILL DOWN"
fi
# verify dante/tinyproxy are alive too
for S in danted tinyproxy; do
  systemctl is-active --quiet "$S" || { logger -t hma-watchdog "$S down — restarting"; systemctl restart "$S"; }
done
EOF
  install -m 644 /dev/stdin /etc/systemd/system/hma-watchdog.service <<'EOF'
[Unit]
Description=HMA tunnel watchdog

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/hma-watchdog
EOF
  install -m 644 /dev/stdin /etc/systemd/system/hma-watchdog.timer <<'EOF'
[Unit]
Description=Run HMA watchdog every 2 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=2min

[Install]
WantedBy=timers.target
EOF
  systemctl daemon-reload
  systemctl enable --now hma-watchdog.timer
  echo "watchdog armed (every 2 min): restarts tunnel/proxies if they die"
fi

# ------------------------------------------------------------- done
step "READY"
cat <<EOF
Systemd services active:
  openvpn-client@hma.service   tunnel (country: $FIRST)
  danted.service               SOCKS5  127.0.0.1:1080
  tinyproxy.service            HTTP    127.0.0.1:$HTTP_PORT
  hma-watchdog.timer           auto-heal (every 2 min)
  hma-netrules.service         SSH survival

Use in apps on this VM (password: $PROXY_PASS — store it somewhere safe):
  export http_proxy=http://$USER_NAME:$PROXY_PASS@127.0.0.1:$HTTP_PORT
  export https_proxy=\$http_proxy
  # or per-app SOCKS5: socks5h://$USER_NAME:$PROXY_PASS@127.0.0.1:1080

Switch countries anytime:   sudo $HERE/select-country.sh <CC>
Check egress:               $HERE/check-egress.sh
EOF
