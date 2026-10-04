# Changelog

## 0.2.0 — 2026-10-04

### Added
- `vps/` proxy kit: `bootstrap.sh` one-command VM setup, systemd tunnel
  watchdog, `select-country.sh` country switcher, `rotate.sh` exit-IP
  rotation with change verification, HTTP proxy (tinyproxy chained through
  dante), SSH-survival routing with optional fail-close
- `bin/hma_account.py`: licensing plane (Vaar-headered), live license
  verification by wallet key, activation-code wrapper, email login
- full documentation set: getting started, tools reference, troubleshooting,
  accounts/licensing deep-dive

### Verified live
- license query over raw HTTP (Vaar envelope + wallet key) against production
- gateway naming model `<CC>.ult.surfeasy.mobi` (DNS, 10+ countries)
- 64-byte XOR key decrypts both DMG defaults and a live install's license data

## 0.1.0 — 2026-10-03

### Added
- reverse engineering of HMA VPN 26.8.0 (macOS): packaging chain, app
  architecture, encrypted defaults (key recovered), update channel, telemetry
- `bin/hma_discover.py` infrastructure discovery
- `bin/hma_probe.py` TCP + IKEv2 responder probes (hand-crafted IKE_SA_INIT)
- `bin/hma_ikev2.py` IKEv2 profile generator (strongSwan / Apple / Windows)
- `bin/hma_wg.py` WireGuard config generator with stdlib X25519 (RFC 7748
  test-vector verified)
