# hma-suite — use HMA's tunnel infrastructure externally

Built from the reverse engineering of `hma_vpn_online.dmg` (HMA VPN 26.8.0,
macOS) — see `docs/RE-REPORT.md`. The suite turns that knowledge into
tools you can run inside your own VM.

**What it is:** discovery + probing of HMA's infrastructure, and generators
for the two *standard* protocols the HMA client speaks (IKEv2 and WireGuard),
so you can connect from Linux/Windows/macOS VMs with your own HMA account.

**What it is not:** a credential bypass. The DMG contains no static VPN
configs — tunnel endpoints and keys are issued per-account by HMA's backend
after login (verified during the RE). Use your own credentials/session.
Bypassing or sharing credentials would violate HMA's terms; connecting with
your own account via a standard protocol is ordinary interoperability.

## Quick start (in the VM)

```bash
# 0. account/licensing — use your own install's wallet key (tested live)
python3 bin/hma_account.py status                     # local install -> live license
python3 bin/hma_account.py licenses --wallet-key XXXXXX-XXXXXX-XXXXXX
python3 bin/hma_account.py activate --code XXXXX-XXXXX-XXXXX   # redeem a key
python3 bin/hma_account.py login --email you@example.com       # all licenses

# 1. see what's reachable & where you egress from (no credentials needed)
python3 bin/hma_discover.py --json report.json

# 2. the practical path — IKEv2 with your HMA credentials
python3 bin/hma_ikev2.py --server GATEWAY --username you@example.com --out hma-out
#    → strongSwan / Apple .mobileconfig / Windows profiles, ready to load

# 3. WireGuard path (when you have keys from your own provisioned session)
python3 bin/hma_wg.py --gen-keypair
python3 bin/hma_wg.py --endpoint GW:51820 --peer-pub SRVPUB \
                      --client-priv YOURPRIV --firewall --out wg0.conf

# 4. validate any endpoint before using it
python3 bin/hma_probe.py --tcp GATEWAY --ports 443,51820
python3 bin/hma_probe.py --ike  GATEWAY            # IKE_SA_INIT responder check
```

Full walkthrough: `docs/VM-SETUP.md`. Protocol-by-protocol reasoning:
`docs/PROTOCOLS.md`.

## Tools

| Tool | Purpose | Network calls |
|---|---|---|
| `hma_discover.py` | NOS SRV bootstrap, geo check, host inventory, TCP probes | unauthenticated only (same as client pre-login) |
| `hma_probe.py` | TCP reachability + minimal IKEv2 `IKE_SA_INIT` responder probe | none (raw sockets to your target) |
| `hma_ikev2.py` | strongSwan swanctl/legacy, Apple `.mobileconfig`, Windows PS | none |
| `hma_wg.py` | `wg-quick` config assembly, X25519 keypair generation (RFC 7748, stdlib) | none |
| `hma_account.py` | license status/queries with your own WalletKey, activation-code redemption, email login | Vaar-headered HTTPS to HMA licensing (same calls the client makes) |

## Files

```
suite/
├── README.md            ← you are here
├── bin/                 ← the five tools (stdlib-only, Python 3.8+)
├── configs/             ← reference templates the generators emit
├── vps/                 ← VPS-as-proxy kit (setup scripts + VPS-GUIDE.md)
└── docs/
    ├── PROTOCOLS.md     ← IKEv2 / WireGuard / Mimic capability map
    ├── ACCOUNTS.md      ← licensing & activation flows (tested live)
    ├── VM-SETUP.md      ← per-OS walkthroughs + troubleshooting
    └── MIMIC.md         ← roadmap for reimplementing Avast's Mimic protocol
```

## Notes

- `hma_wg.py --gen-keypair` uses a self-contained X25519 implementation
  (verified against RFC 7748 test vectors); keys never leave the VM.
- `hma_ikev2.py` embeds your password in the generated files only if you pass
  it; the secrets files are written `0600` and should stay on the VM.
- The IKE prober sends a single well-formed IKE_SA_INIT; any reply (even a
  NO_PROPOSAL notification) proves a responder. Timeouts are inconclusive —
  many networks filter outbound UDP 500/4500.
