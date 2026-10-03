#!/usr/bin/env bash
# check-egress.sh — verify what IP the proxy (and the VPS itself) present.
#
# Usage:
#   ./check-egress.sh                          # via ssh-forwarded proxy on :1080
#   ./check-egress.sh 1.2.3.4 1080 user pass   # direct to a --public proxy
set -uo pipefail

INFO=https://ip-info.ff.avast.com/v2/info   # HMA's own geo endpoint, no auth

if [ $# -ge 1 ]; then
  HOST=$1; PORT=${2:-1080}; USER=${3:-}; PASS=${4:-}
  AUTH=""; [ -n "$USER" ] && AUTH="--proxy-user $USER:$PASS"
  CURLARGS=(--socks5-hostname "$HOST:$PORT" $AUTH)
else
  # default: ssh-forwarded local proxy
  CURLARGS=(--socks5-hostname 127.0.0.1:1080)
fi

echo "== egress seen by the proxy:"
curl -sS -m 12 "${CURLARGS[@]}" "$INFO" | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    print('  IP        : %s' % d.get('ip'))
    print('  location  : %s, %s' % (d.get('city'), d.get('countryName')))
    print('  network   : %s' % d.get('organization'))
except Exception as e:
    print('  (unparseable response: %s)' % e)
"

echo "== VPS's own egress (no proxy):"
curl -sS -m 12 "$INFO" | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    print('  IP        : %s' % d.get('ip'))
    print('  location  : %s, %s' % (d.get('city'), d.get('countryName')))
except Exception as e:
    print('  (unparseable response: %s)' % e)
" 2>/dev/null || echo "  (curl failed — expected if running from inside the VPS with kill-switch rules)"

echo
echo "If the two IPs differ, the proxy is riding the tunnel correctly."
