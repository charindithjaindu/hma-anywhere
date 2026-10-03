# VM setup guide

All tools are Python 3.8+ stdlib only — no pip needed. Copy the `suite/`
folder into the VM however you like (shared folder, scp, USB).

```
suite/
├── bin/
│   ├── hma_discover.py   # infrastructure discovery (no credentials)
│   ├── hma_probe.py      # TCP + IKE-SA_INIT endpoint validation
│   ├── hma_ikev2.py      # IKEv2 profile generator (credentials path)
│   └── hma_wg.py         # WireGuard wg-quick generator (session-keys path)
└── ...
```

## Step 0 — discovery & validation (any OS)

```bash
python3 bin/hma_discover.py --json report.json
python3 bin/hma_probe.py --tcp mac-vpn.u.avcdn.net --ports 443
```

The discover report shows which Avast/HMA infrastructure is reachable from
your network and your egress IP as their geo service sees it. VPN *server*
endpoints are not in this list (they're auth-gated); grab the per-location
gateway hostname from your HMA account's manual-configuration resources.

## Step 1 — pick your path

### Path A: IKEv2 (recommended; needs only HMA username/password)

**Debian/Ubuntu VM (strongSwan):**

```bash
sudo apt-get install -y strongswan strongswan-swanctl libcharon-extra-plugins \
                        libstrongswan-extra-plugins
python3 bin/hma_ikev2.py --server GATEWAY --username you@example.com --out hma-out
sudo cp hma-out/strongswan/swanctl.conf /etc/swanctl/conf.d/hma.conf
sudo swanctl --load-all
sudo swanctl --initiate --child hma-child
sudo swanctl --terminate --ike hma        # disconnect
sudo swanctl --list-sas                   # verify SAs
```

Notes:
- Install `libcharon-extra-plugins`/`libstrongswan-extra-plugins` so EAP-MSCHAPv2
  is present (`eap-mschapv2` plugin); Debian's split packaging omits it by default.
- Check the log if anything fails: `sudo journalctl -u strongswan-swanctl -f`.
- Legacy-style systems (no swanctl): use `hma-out/legacy/ipsec.conf` +
  `ipsec.secrets`, then `sudo ipsec restart && sudo ipsec up hma`.

**Windows VM:** run `hma-out/windows/connect.ps1` as Administrator, then
connect from Settings → Network → VPN (enter credentials on first connect).

**macOS VM:** `sudo profiles install -path hma-out/apple/HMA-iKEv2.mobileconfig`
(or double-click), password field is embedded if you passed it, otherwise
prompts. System Settings → VPN shows the profile.

Verify from any of them:

```bash
python3 bin/hma_discover.py --json after.json   # egress IP/country should change
curl https://ip-info.ff.avast.com/v2/info        # same check, raw
```

### Path B: WireGuard (needs keys from an authorized session)

```bash
python3 bin/hma_wg.py --gen-keypair
# provision the generated PublicKey with HMA (router-config flow / your session),
# obtain the server's PublicKey + your tunnel address, then:
python3 bin/hma_wg.py --endpoint GATEWAY:51820 \
    --peer-pub SERVERPUBKEYBASE64 --client-priv YOURPRIVKEYBASE64 \
    --address 10.8.0.2/32 --firewall --out wg0.conf
sudo apt-get install -y wireguard
sudo wg-quick up wg0
sudo wg show
```

`--firewall` installs the same kill-switch semantics the macOS client uses
(all traffic must traverse the tunnel; wg fwmark + policy routing).

### Path C: what NOT to bother with

- Running the extracted macOS `mimictun`/`wireguardtun` Mach-O binaries in a
  Linux VM: they're darwin-linked Go binaries; they will not run. WireGuard
  reimplementation is pointless (wg-quick IS the same protocol). Mimic needs a
  protocol reimplementation — see `MIMIC.md`.
- Expecting the suite to mint working configs from the DMG alone: no static
  keys exist in the package (verified during the RE). Tunnel parameters are
  issued per-account by HMA's backend.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `--ike` probe: "inconclusive, no reply" | Your network blocks outbound UDP 500/4500 — try another network or use TCP-443-based paths |
| strongSwan `no acceptable proposal` | Gateway wants different ciphers; drop the `!`-pinned proposals in the generated config |
| EAP failure immediately | Wrong auth flavor — try `--eap md5` or check your HMA credential type |
| wg handshake never completes | Endpoint wrong, or keys not provisioned for your account |
