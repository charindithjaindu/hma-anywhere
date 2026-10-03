#!/usr/bin/env bash
# rotate.sh — reshuffle the exit IP (HMA's "IP Shuffle", client flag `ipShuffle`).
#
# Restarts the tunnel (picking a different gateway when the config lists
# several) and VERIFIES the egress IP actually changed, retrying a few times.
#
# Usage:
#   sudo ./rotate.sh                 # rotate within the current country
#   sudo ./rotate.sh --attempts 5    # more patience before giving up
set -euo pipefail

ATTEMPTS=3
[ "${1:-}" = "--attempts" ] && ATTEMPTS="${2:-3}"
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }

UNIT=openvpn-client@hma.service
INFO=https://ip-info.ff.avast.com/v2/info

tunif() { ls /sys/class/net | grep -m1 -E '^(tun|utun|ppp|ovpn)[0-9]*' || true; }
egress_ip() {
    local IF; IF=$(tunif)
    [ -n "$IF" ] || return 1
    curl -sS -m 10 --interface "$IF" "$INFO" 2>/dev/null \
        | python3 -c "import json,sys;print(json.load(sys.stdin).get('ip',''))" 2>/dev/null || true
}

# multi-remote configs: make sure OpenVPN randomizes across them
CONF=$(readlink /etc/openvpn/client/hma.conf 2>/dev/null || echo /etc/openvpn/client/hma.conf)
N_REMOTES=$(grep -c '^remote ' "$CONF" 2>/dev/null || echo 0)
if [ "$N_REMOTES" -gt 1 ] && ! grep -q '^remote-random' "$CONF"; then
    echo "config has $N_REMOTES remotes — enabling remote-random"
    echo "remote-random" >> "$CONF"
fi

OLD=$(egress_ip || true)
echo "current egress: ${OLD:-unknown}"

for i in $(seq 1 "$ATTEMPTS"); do
    echo "restart #$i ..."
    systemctl restart "$UNIT"
    # wait for the tunnel interface to come back
    for _ in $(seq 1 15); do [ -n "$(tunif)" ] && systemctl is-active --quiet "$UNIT" && break; sleep 2; done
    NEW=$(egress_ip || true)
    if [ -n "$NEW" ] && [ "$NEW" != "$OLD" ]; then
        echo "rotated: $OLD  ->  $NEW"
        exit 0
    fi
    echo "  egress still ${NEW:-down}${OLD:+ (was $OLD)} — retrying"
    sleep 3
done

echo "WARNING: egress IP unchanged after $ATTEMPTS attempts."
echo "If the config has a single 'remote' line, the gateway LB may pin your IP;"
echo "add more configs for this country or switch country via select-country.sh."
exit 1
