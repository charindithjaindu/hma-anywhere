#!/usr/bin/env bash
# select-country.sh — switch the HMA tunnel to another country.
#
# Expects one OpenVPN config per country, named by 2-letter country code:
#     /etc/openvpn/hma/US.conf, GB.conf, DE.conf, ...
# (Copy the per-location .ovpn files from your HMA account's manual-setup /
#  router section into /etc/openvpn/hma/ and rename to <CC>.conf.
#  Gateways use the pattern <CC>.ult.surfeasy.mobi — verified live: the client
#  itself stores locations as IN/CH/JP/GB/AU/... .ult.surfeasy.mobi.)
#
# Usage:
#   select-country.sh --list            # show installed countries + active one
#   sudo select-country.sh DE           # switch tunnel to Germany
#   sudo select-country.sh current      # print active country
#
# The dante SOCKS proxy (external: tun0) keeps running untouched across
# switches — apps pointed at 127.0.0.1:1080/8888 just change egress country.
set -euo pipefail

CONF_DIR=/etc/openvpn/hma
UNIT=openvpn-client@hma.service
ACTIVE_LINK=/etc/openvpn/hma/.active

# ---- country code table (subset for --list readability; any <CC>.conf works)
NAMES="US=United States GB=United Kingdom DE=Germany FR=France NL=Netherlands
CH=Switzerland JP=Japan IN=India AU=Australia CA=Canada SG=Singapore IT=Italy
ES=Spain SE=Sweden PL=Poland BR=Brazil AE=United Arab Emirates TR=Turkey"

name_for() {
    for kv in $NAMES; do [ "${kv%%=*}" = "$1" ] && echo "${kv#*=}" && return; done
    echo "$1"
}

cmd="${1:-current}"

case "$cmd" in
    --list|list)
        echo "installed country configs in $CONF_DIR:"
        for f in "$CONF_DIR"/*.conf; do
            [ -e "$f" ] || { echo "  (none — copy <CC>.conf files there first)"; break; }
            cc=$(basename "$f" .conf)
            printf "  %-4s %s\n" "$cc" "$(name_for "$cc")"
        done
        [ -L "$ACTIVE_LINK" ] && echo "active: $(basename "$(readlink "$ACTIVE_LINK")" .conf)"
        exit 0 ;;
    current)
        if [ -L "$ACTIVE_LINK" ]; then
            cc=$(basename "$(readlink "$ACTIVE_LINK")" .conf)
            echo "$cc ($(name_for "$cc"))"
        else
            echo "no country selected yet"
            exit 1
        fi
        exit 0 ;;
esac

CC=$(echo "$cmd" | tr '[:lower:]' '[:upper:]')
TARGET="$CONF_DIR/$CC.conf"
[ -f "$TARGET" ] || {
    echo "no config for '$CC' — expected $TARGET" >&2
    echo "install per-country .ovpn files from your HMA account, renamed to <CC>.conf" >&2
    echo "known so far: $("$0" --list 2>/dev/null | sed -n 's/^  \(..\) .*/\1/p' | tr '\n' ' ')" >&2
    exit 1
}

[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }

# normalize: ensure auth file reference and stable service name
if ! grep -q '^auth-user-pass' "$TARGET"; then
    echo "auth-user-pass $CONF_DIR/hma.creds" >> "$TARGET"
    echo "(added auth-user-pass directive → $CONF_DIR/hma.creds)"
fi
if [ ! -f "$CONF_DIR/hma.creds" ] && [ -n "${HMA_USER:-}" ]; then
    printf '%s\n%s\n' "$HMA_USER" "${HMA_PASS:?set HMA_PASS too}" > "$CONF_DIR/hma.creds"
    chmod 600 "$CONF_DIR/hma.creds"
fi

mkdir -p /etc/openvpn/client
ln -sfn "$TARGET" /etc/openvpn/client/hma.conf
systemctl restart "$UNIT"
sleep 3
systemctl is-active "$UNIT" >/dev/null || {
    echo "tunnel failed to come up — journalctl -u $UNIT -n 30" >&2
    exit 2
}
ln -sfn "$TARGET" "$ACTIVE_LINK"

TUNIF=$(ls /sys/class/net | grep -m1 -E '^(tun|utun|ppp|ovpn)[0-9]*' || true)
echo "switched to $CC ($(name_for "$CC")) — tunnel iface: ${TUNIF:-?}"
echo "verify:  curl --interface ${TUNIF:-tun0} -sS https://ip-info.ff.avast.com/v2/info"
echo "         ./check-egress.sh"
