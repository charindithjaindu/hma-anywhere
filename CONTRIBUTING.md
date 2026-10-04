# Contributing

Thanks for considering a contribution! This project documents and drives a
commercial VPN service's undocumented interfaces, so a few ground rules:

## Ground rules

1. **No credential abuse features.** PRs that scrape/share other people's
   credentials, farm trials, or bypass device limits will be rejected.
2. **No vendor code in the repo.** Anything extracted from HMA/Avast binaries
   (configs, certificates, proprietary payloads) stays out of git — describe
   it in the docs instead.
3. **Test against your own subscription** and redact identifiers (wallet keys,
   device UUIDs, license IDs) from logs and screenshots before posting.

## Good first contributions

- additional distro support for the vps/ scripts (RHEL/Fedora/Alpine)
- more per-country gateway notes for [docs/PROTOCOLS.md](docs/PROTOCOLS.md)
- systemd hardening (sandboxing directives for danted/tinyproxy units)
- docs improvements — they're the front door

## Mechanics

- Python tools: stdlib only, 3.8+ compatible, `python3 -m py_compile` clean
- Shell scripts: `bash -n` clean, target Debian/Ubuntu but don't break others
- CI runs both plus a smoke test (`--help`) on every push — keep it green
- Small PRs beat big ones; one logical change per PR
