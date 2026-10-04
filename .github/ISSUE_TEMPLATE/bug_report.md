---
name: Bug report
about: Something doesn't work as documented
labels: bug
---
**What were you trying to do?** (command + full output)

**Environment**
- OS/distro: 
- Python version (`python3 --version`): 
- Where: VM / VPS / bare metal
- Tunnel path: OpenVPN / IKEv2 / WireGuard

**Diagnostics** (from [TROUBLESHOOTING](../../docs/TROUBLESHOOTING.md)):
```
./check-egress.sh
systemctl status openvpn-client@hma danted tinyproxy
journalctl -u openvpn-client@hma -n 50 --no-pager
```

⚠️ Redact wallet keys, activation codes, device UUIDs and public IPs before posting.
