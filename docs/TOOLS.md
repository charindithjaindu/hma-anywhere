# Tools reference

All Python tools are **stdlib-only** (Python 3.8+, no pip installs). Bash
scripts target Debian/Ubuntu. Nothing here contacts HMA's servers except
`hma_account.py` and `hma_discover.py` — every network call is documented
per tool.

Quick index:

| Tool | One-liner |
|---|---|
| [`hma_account.py`](#hma_accountpy) | license status, verification, activation, login |
| [`hma_discover.py`](#hma_discoverpy) | map HMA's infrastructure, check your egress |
| [`hma_probe.py`](#hma_probepy) | is this gateway reachable / speaking IKEv2? |
| [`hma_ikev2.py`](#hma_ikev2py) | generate IKEv2 profiles for every OS |
| [`hma_wg.py`](#hma_wgpy) | generate WireGuard configs / keypairs |
| [`bootstrap.sh`](#bootstrapsh) | fresh VM → working proxies, one command |
| [`setup-proxy.sh`](#setup-proxysh) | install the SOCKS5/HTTP proxy pair |
| [`select-country.sh`](#select-countrysh) | switch egress country |
| [`rotate.sh`](#rotatesh) | new exit IP in the same country |
| [`setup-netrules.sh`](#setup-netrulessh) | SSH survival under a full tunnel |
| [`check-egress.sh`](#check-egresssh) | verify egress IP/geo |

---

## bin/hma_account.py

Account and licensing plane. Authenticates exactly like the official client
(`Vaar-Header-*` envelope) and only ever with credentials you own.

```bash
# auto-detect a local HMA install (macOS) and check the license live
python3 bin/hma_account.py status

# VM-native: verify a license with its wallet key
python3 bin/hma_account.py licenses --wallet-key XXXXXX-XXXXXX-XXXXXX

# redeem an activation code (needs the HMA app installed on this machine —
# on a fresh VM it prints the two one-time alternatives instead)
python3 bin/hma_account.py activate --code XXXXX-XXXXX-XXXXX-XXXXX

# full email login → list every license on the account
# (password prompted interactively, or env HMA_PASSWORD)
python3 bin/hma_account.py login --email you@example.com
```

Network: `POST https://my-mac.ff.avast.com/v1/query/get-exact-application-licenses`
(JSON + Vaar headers). `activate`/`login` shell out to the vendor CLI when
present (protobuf codec). Details: [ACCOUNTS.md](ACCOUNTS.md).

## bin/hma_discover.py

Replays the client's unauthenticated discovery: NOS SRV bootstrap, geo
lookup, host inventory with TCP probes. No credentials involved — same
requests the app makes before login.

```bash
python3 bin/hma_discover.py                  # human-readable report
python3 bin/hma_discover.py --json out.json  # machine-readable
python3 bin/hma_discover.py --no-probe       # skip TCP probes
```

## bin/hma_probe.py

Reachability checks for a candidate gateway.

```bash
python3 bin/hma_probe.py --tcp GATEWAY --ports 443,51820
python3 bin/hma_probe.py --ike GATEWAY          # minimal IKE_SA_INIT probe
python3 bin/hma_probe.py --ike GATEWAY --ports 500,4500 --timeout 6
```

`--ike` sends one well-formed IKEv2 SA_INIT; **any** reply (even an error
notification) proves a responder. A timeout is *inconclusive* — many
networks filter outbound UDP 500/4500.

## bin/hma_ikev2.py

Generates IKEv2 profiles for four platforms from one gateway + your HMA
account credentials. Ciphers pinned to AES-256/SHA-256/DH14 to match the
client's own proposals.

```bash
python3 bin/hma_ikev2.py --server GATEWAY --username you@example.com \
    [--password ...] [--remote-id ID] [--eap mschapv2] [--name hma] \
    [--out hma-out]
# → hma-out/strongswan/swanctl.conf   (Linux, modern)
#   hma-out/legacy/ipsec.conf+secrets (Linux, starter)
#   hma-out/apple/HMA-iKEv2.mobileconfig  (macOS/iOS)
#   hma-out/windows/connect.ps1           (Windows 10/11)
```

Secrets files are written `0600`. Bring it up:
`sudo swanctl --load-all && sudo swanctl --initiate --child hma-child`.

## bin/hma_wg.py

WireGuard config assembly and local key generation (X25519 implemented in
pure Python, verified against RFC 7748 test vectors; keys never leave the
machine).

```bash
# fresh client keypair
python3 bin/hma_wg.py --gen-keypair

# full config once you have the server's public key + your provisioned key
python3 bin/hma_wg.py --endpoint GW:51820 \
    --peer-pub SERVERPUBKEY --client-priv YOURPRIVKEY \
    --address 10.8.0.2/32 --firewall --mtu 1420 --out wg0.conf
# then: sudo wg-quick up wg0
```

`--firewall` adds kill-switch PostUp/PostDown rules (fwmark policy routing —
traffic must traverse the tunnel or it's rejected). `wg0.conf` is written
`0600`.

---

## vps/bootstrap.sh

The orchestrator — see the [Getting started](GETTING-STARTED.md) walkthrough.

```bash
sudo ./bootstrap.sh --countries US,GB \
    [--code KEY] [--wallet-key KEY] \
    [--proxy-user danteproxy] [--proxy-pass PASS] \
    [--http-port 8888] [--no-watchdog]
```

Installs packages → SSH-survival rules → license check/redeem → waits for
per-country configs → proxies → first tunnel → watchdog. Resume-safe: exits
with exact instructions where a manual step is pending.

## vps/setup-proxy.sh

```bash
sudo ./setup-proxy.sh [--user NAME] [--password PASS] \
    [--http 8888] [--public --allow YOUR_IP/32]
```

- SOCKS5 via **dante**: `external:` is bound to the tunnel interface — the
  fail-closed guarantee (tunnel down ⇒ proxied connections fail, no leak).
- HTTP via **tinyproxy** chained into dante (`--http`).
- Default listener is `127.0.0.1` only. `--public` requires `--allow` and
  adds an iptables restriction — think twice before exposing it.
- `TUNIF=wg0 sudo ./setup-proxy.sh` to pin a non-auto-detected interface.

## vps/select-country.sh

```bash
sudo ./select-country.sh --list     # installed countries + active one
sudo ./select-country.sh US         # switch (symlink + restart tunnel)
./select-country.sh current         # what country am I on?
```

Expects `/etc/openvpn/hma/<CC>.conf` files (renamed from HMA's per-location
`.ovpn` downloads). The proxies keep running through switches.

## vps/rotate.sh

```bash
sudo ./rotate.sh [--attempts 5]
```

Restarts the tunnel (enabling `remote-random` for multi-server configs) and
**verifies via HMA's geo endpoint that the egress IP actually changed** —
retries before giving up, and explains your options if the gateway pins the
IP.

## vps/setup-netrules.sh

```bash
sudo ./setup-netrules.sh [--failclose]
```

Run **before** the first tunnel. Adds a policy rule so traffic sourced from
the VPS public IP keeps the original route (SSH survives the full tunnel);
`--failclose` additionally drops all non-tunnel egress while no tunnel
exists. Installed as `hma-netrules.service` so it re-applies at boot.

## vps/check-egress.sh

```bash
./check-egress.sh                      # via local proxy (127.0.0.1:1080)
./check-egress.sh HOST 1080 user pass  # via a remote --public proxy
```

Compares the IP/geo seen **through the proxy** against the VPS's own egress,
using HMA's own pre-auth geo endpoint.
