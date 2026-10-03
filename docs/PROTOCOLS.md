# HMA tunnel protocols — what works externally and how

This document maps the three protocols HMA VPN 26.8.0 (macOS) speaks, based on
the reverse engineering in `RE-REPORT.md`, to what you can actually
use from your own VM. Honest capability matrix first:

| Protocol | In the client | Works externally? | Needs |
|---|---|---|---|
| IKEv2/IPsec | Apple `IKEv2Provider` via `VPN.framework` (`ikev2Connector`) | **Yes — standard protocol, only your HMA credentials** | server hostname + HMA username/password |
| WireGuard | `com.privax.osx.provpn.wireguardtun` (Go, zx2c4) | Yes, with session keys | server pubkey + your provisioned key |
| "Morphing" (Mimic) | `com.privax.osx.provpn.mimictun` (Go, Avast-internal) | Not without a reimplementation | see `MIMIC.md` |

Key structural fact: **the DMG contains no static VPN configs or keys.** All
three paths receive their tunnel parameters (server endpoints, keys, certs)
from HMA's authenticated backend (AVAPI over NOS, protobuf, TCP 443/7500 —
bootstrap via `_nos._tcp.nos.avast.com` SRV). That's why `ikev2.hidemyass.com`
doesn't even resolve in public DNS: the client learns real endpoints after
login. So "use them externally" means feeding the suite an endpoint + the
credentials you're entitled to.

## 1. IKEv2/IPsec — the practical path

- The GUI hardcodes `ikev2.hidemyass.com` and drives Apple's
  `com.apple.NetworkExtension.IKEv2Provider` (whitelisted in the decrypted
  `killswitch.dfl` alongside `com.apple.route`). Apple's provider does EAP —
  i.e., username/password — which is why this path needs nothing exotic.
- HMA documents manual IKEv2/OpenVPN/WireGuard setup for subscribers on their
  support site; the per-location gateway hostname you supply to
  `hma_ikev2.py --server ...` comes from there (or your dashboard).
- Generated artifacts: strongSwan `swanctl.conf`, legacy `ipsec.conf` +
  `ipsec.secrets`, an unsigned Apple `.mobileconfig`, and a Windows
  `Add-VpnConnection` script. Ciphers pinned to AES-256/SHA-256/DH14 to match
  the client's own proposal strings (`aes256-sha256-modp2048`).
- Validate a candidate gateway first: `python3 bin/hma_probe.py --ike HOST`.

## 2. WireGuard

- The client's engine is stock zx2c4 WireGuard userspace (same library family
  as `wg-quick`), with HMA session management wrapped around it. From mimictun
  strings we know the userland netstack sits in front (`--ifscope` binding,
  split tunnel marks), but the wire format is plain WireGuard.
- Your side: create a fresh client keypair with `hma_wg.py --gen-keypair`
  (local-only X25519), provision it in whatever authorized path you use, then
  `hma_wg.py` assembles `wg0.conf` with kill-switch rules equivalent to the
  client's `killswitch.dfl` semantics (iptables/fwmark, not per-app signatures
  — Linux can't easily do the teamId/bundleId gating the macOS filter does).
- Where to get the server side legitimately: HMA's router/WireGuard config
  generation for your own account, or your own provisioned session.

## 3. Mimic ("morphing protocol") — client-internal

- GUI names: `com.vpn.morphing`, marketed as "A fast and secure protocol made
  by our experts to bypass VPN restrictions" (`vpn_proto_mimic_title`).
- Encapsulation: WireGuard-in-TLS1.3 with PQE (MLKEM1024-P384) and optional
  ECH. The macOS binary is a fully-functional CLI (`-local -remote -ca
  -tlsdomain -ech-public-key -pqtls ...`) but is darwin-only and talks the
  undocumented protobuf Mimic protocol (`mimic-core`: Greeted→Open handshake,
  weaver/looper streams, pqe-join).
- Reimplementing it on Linux is a real project; see `MIMIC.md`.

## Backend services (context)

| Service | Host | Auth |
|---|---|---|
| NOS gateway bootstrap | `_nos._tcp.nos.avast.com` SRV → `nos.lops.akadns.net:443/7500` | protobuf AVAPI, auth-gated |
| Program updates | `mac-vpn.u.avcdn.net/mac-vpn-gen/10_13` | none (RSA-signed payloads) |
| Remote config | `shepherd.avcdn.net` | none |
| Geo/IP | `ip-info.ff.avast.com/v2/info` | none |
| Accounts/licensing | `my-mac.ff.avast.com`, `alpha-*.ff.avast.com`, `id.hidemyass.com` | token/EAP-gated |
| Telemetry | `analytics.ff.avast.com`, `submit.sb.avast.com` | none (that's the point) |

The discovery tool exercises only the unauthenticated rows — the same requests
the client makes before you log in.
