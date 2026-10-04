# Security policy

## Scope

This toolkit handles credentials (wallet keys, account passwords, VPN keys)
and modifies network configuration on the machines it runs on.

## Reporting

- Found a vulnerability **in this repo's code** (e.g. credential leakage in
  a tool, injection in the shell scripts)? Open a GitHub security advisory
  via the "Security" tab rather than a public issue.
- Found a vulnerability **in HMA/Avast's service**? Report it to
  [Gen Digital's bug bounty](https://www.gendigital.com/) — do not open an
  issue here.

## Handling credentials safely

- Never paste wallet keys, activation codes, or tokens into issues, PRs, or
  chats — logs and screenshots included.
- Generated secret files (`wg0.conf`, `ipsec.secrets`, `hma.creds`) are
  written `0600` and git-ignored; keep it that way.
