#!/usr/bin/env bash
# setup-netrules.sh — keep SSH alive while the VPS runs a full VPN tunnel.
#
# Run this BEFORE bringing the tunnel up. It:
#   1. snapshots the original default route (interface + gateway),
#   2. adds a policy rule: traffic sourced from the VPS public IP uses the
#      original route (table 200) — your SSH sessions survive the tunnel,
#   3. optionally (--failclose) drops ALL other outbound traffic while the
#      tunnel interface is down (kill-switch).
#
# Installs /usr/local/sbin/hma-netrules + a systemd unit so rules re-apply on boot.
#
# Usage:
#   sudo ./setup-netrules.sh             # SSH-survival only
#   sudo ./setup-netrules.sh --failclose # also block non-tunnel egress
set -euo pipefail

FAILCLOSE=0
[ "${1:-}" = "--failclose" ] && FAILCLOSE=1
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }

PUBIF=$(ip -4 route show default | awk '{print $5; exit}')
GW=$(ip -4 route show default | awk '{print $3; exit}')
PUBIP=$(ip -4 -o addr show dev "$PUBIF" scope global | awk '{split($4,a,"/"); print a[1]; exit}')
echo "public: $PUBIF ($PUBIP) via $GW"

install -m 755 /dev/stdin /usr/local/sbin/hma-netrules <<EOF
#!/usr/bin/env bash
set -e
PUBIF=$PUBIF; GW=$GW; PUBIP=$PUBIP; FAILCLOSE=$FAILCLOSE
# SSH survival: anything sourced from the public IP uses the original route
ip rule del from \$PUBIP lookup 200 2>/dev/null || true
ip rule add from \$PUBIP lookup 200
ip route replace table 200 default via \$GW dev \$PUBIF
# fail-close: reject egress while the tunnel interface is absent
if [ "\$FAILCLOSE" = 1 ]; then
  TUNIF=\$(ls /sys/class/net | grep -m1 -E '^(tun|utun|ppp|wg|ovpn)[0-9]*' || true)
  if [ -z "\$TUNIF" ]; then
    iptables -C OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT 2>/dev/null || \\
      iptables -I OUTPUT 1 -m state --state ESTABLISHED,RELATED -j ACCEPT
    iptables -C OUTPUT -o lo -j ACCEPT 2>/dev/null || iptables -I OUTPUT 1 -o lo -j ACCEPT
    iptables -C OUTPUT ! -o \$PUBIF -j ACCEPT 2>/dev/null || \\
      iptables -I OUTPUT 1 ! -o \$PUBIF -j ACCEPT
    iptables -C OUTPUT -o \$PUBIF -m mark --mark 0x2 -j ACCEPT 2>/dev/null || \\
      iptables -I OUTPUT 1 -o \$PUBIF -m mark --mark 0x2 -j ACCEPT
    # mark SSH-server replies so established sessions keep flowing
    iptables -t mangle -C OUTPUT -p tcp --sport 22 -j MARK --set-mark 0x2 2>/dev/null || \\
      iptables -t mangle -A OUTPUT -p tcp --sport 22 -j MARK --set-mark 0x2
  fi
fi
EOF

install -m 644 /dev/stdin /etc/systemd/system/hma-netrules.service <<'EOF'
[Unit]
Description=HMA VPS SSH-survival routing
DefaultDependencies=no
Before=network-online.target
Wants=network-pre.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/hma-netrules
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable hma-netrules
/usr/local/sbin/hma-netrules
echo "rules active. SSH sourced from $PUBIP will bypass the tunnel; everything else rides it."
[ "$FAILCLOSE" = 1 ] && echo "fail-close ON: outbound traffic is dropped while no tunnel exists."
echo
echo "WARNING: verify you can still reach the box, and keep provider console access handy."
