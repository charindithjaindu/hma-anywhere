# hma-suite

**Use your own HMA VPN subscription from a Linux VM or VPS — through standard
protocols (IKEv2 / WireGuard / OpenVPN), exposed to your apps as local
SOCKS5/HTTP proxies, with per-country server selection and IP rotation.**

Built by reverse engineering the official HMA VPN 26.8.0 client for macOS
([full technical report](docs/RE-REPORT.md)). Everything here works with
**your own account and your own credentials** — nothing bypasses HMA's
authentication; it simply speaks the same protocols their client does, in
places their client doesn't run.

---

## What is this?

HMA's desktop apps exist for macOS/Windows/iOS/Android, and their Linux
support is manual config files. This suite fills the gap for servers and
VMs:

```
your apps (on a VM/VPS)
   │  point at 127.0.0.1 — nothing else to configure
   ▼
┌─────────────────────────────────────────────────┐
│  VPS                                            │
│   SOCKS5 :1080 ─┐                               │
│   HTTP   :8888 ─┤ dante/tinyproxy               │
│                 │ pinned to the tunnel (fail-    │
│                 ▼ closed: no leak if VPN drops) │
│           HMA tunnel  ────▶  <CC>.ult.surfeasy.mobi
└─────────────────────────────────────────────────┘
   egress = HMA gateway, country of your choice
```

- **Choose your country** — switch anytime, proxies stay up
  (`select-country.sh JP`)
- **Rotate your exit IP** — verified reconnection, same country
  (`rotate.sh`)
- **Self-healing** — a systemd watchdog restarts the tunnel/proxies if they
  die; everything survives reboots

## What you need

| You have | What to do |
|---|---|
| Activation key only | Redeem it once (browser or one command) — see [Getting started](docs/GETTING-STARTED.md#step-1-activate-your-subscription) |
| Active HMA subscription | Skip straight to the VM setup |
| Nothing yet | This toolkit can't help — it's not a VPN provider 🙂 |

Two things are **deliberately manual** (both are behind HMA's own login, and
this project doesn't scrape authenticated web portals):
1. redeeming an activation code the first time (browser or one command on a
   machine with the HMA app), and
2. downloading the per-country OpenVPN configs from your HMA dashboard.

Everything after that is one command.

## Quick start

On a Debian/Ubuntu VM or VPS:

```bash
# 1. clone
git clone https://github.com/charindithjaindu/hma-suite.git
cd hma-suite/vps

# 2. drop your per-country configs in place (from your HMA dashboard)
#    /etc/openvpn/hma/US.conf  GB.conf  DE.conf ...

# 3. one command: packages + routing + proxies + tunnel + watchdog
sudo ./bootstrap.sh --countries US,GB

# 4. point your apps at localhost — done
export http_proxy=http://danteproxy:PASSWORD@127.0.0.1:8888
export https_proxy=$http_proxy
```

Then, whenever you feel like it:

```bash
sudo ./select-country.sh JP    # move egress to Japan (~5 s, proxies untouched)
sudo ./rotate.sh               # new exit IP, same country
./check-egress.sh              # prove where you're egressing from
```

Full walkthrough (including the activation-key-only path):
**[docs/GETTING-STARTED.md](docs/GETTING-STARTED.md)**.

## What's in the box

```
bin/                     Python 3.8+ tools, stdlib only, no dependencies
  hma_account.py         license status/verification, activation, login
  hma_discover.py        infrastructure discovery + geo check (no credentials)
  hma_probe.py           TCP + IKEv2 responder probes for gateways
  hma_ikev2.py           IKEv2 profile generator (strongSwan/Apple/Windows)
  hma_wg.py              WireGuard config generator + X25519 keypair tool
vps/                     the VPS kit (bash)
  bootstrap.sh           one-command setup, resume-safe
  setup-proxy.sh         SOCKS5 + HTTP proxies, fail-closed to the tunnel
  select-country.sh      country switcher
  rotate.sh              exit-IP rotation with change verification
  setup-netrules.sh      SSH-survival routing under a full tunnel
  check-egress.sh        egress IP/geo verification
configs/                 reference output examples
```

## Documentation

| Doc | Read it for |
|---|---|
| [Getting started](docs/GETTING-STARTED.md) | **start here** — activation key to working proxy, step by step |
| [Tools reference](docs/TOOLS.md) | every command, flag and example |
| [Troubleshooting](docs/TROUBLESHOOTING.md) | when something doesn't work |
| [VPS guide](vps/VPS-GUIDE.md) | the proxy architecture in depth |
| [Protocols](docs/PROTOCOLS.md) | which HMA protocols work externally and why |
| [Accounts & licensing](docs/ACCOUNTS.md) | how the licensing plane works (tested live) |
| [RE report](docs/RE-REPORT.md) | the full reverse-engineering write-up |
| [Mimic roadmap](docs/MIMIC.md) | reimplementing HMA's proprietary protocol |

## Responsible use

- **Your subscription, your credentials.** The tools authenticate as you and
  count against your device slots (typically 5). Don't share keys or tokens.
- Not affiliated with HMA, Privax, or Gen Digital. This is independent
  interoperability research and tooling; HMA's terms of service still apply
  to how you use their service.
- Don't expose the proxies to the internet — they bind to localhost by
  default for a reason. An open proxy gets abused within minutes.
- Provided as-is for personal use; you're responsible for compliance with
  your VPN provider's terms and your local laws.

## Status

- License-plane APIs: **tested live** against production (see
  [ACCOUNTS.md](docs/ACCOUNTS.md))
- Tunnel paths: IKEv2 + WireGuard + OpenVPN configs (HMA's official Linux path)
- Mimic (HMA's proprietary protocol): documented, not reimplemented —
  [roadmap](docs/MIMIC.md)
