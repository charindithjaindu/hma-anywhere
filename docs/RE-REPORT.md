# HMA VPN for macOS — Reverse Engineering Report

**Sample:** `hma_vpn_online.dmg` (62,765,702 bytes)
**SHA-256:** `19c86575894a16e91525de7690256033dba78d4c6d1a5a4d99113857b331c7a6`
**Product:** HMA VPN (Hide My Ass) 26.8.0 for macOS — bundle `com.privax.osx.provpn`
**Vendor:** Privax Ltd / Gen Digital (formerly Avast). Codesign TeamID `96HLSU34RN`, hardened runtime, notarized timestamp 4 Sep 2026.

## 1. Packaging & installer chain

The DMG is an **"online installer"**: a small stub that stages the real package.

```
hma_vpn_online.dmg
├── config.tar                  ← attribution data: EDAT/ECOO = "mmm_hma_998_888_000_m"
└── HMA VPN.pkg                 ← product pkg, id com.privax.osx.provpn, v26.8.0
    ├── Distribution            ← requires macOS ≥ 10.13, universal x86_64+arm64,
    │                             refuses install if HMA already present
    └── hmavpn.pkg
        ├── Payload (cpio.gz)   → VPNHMA.raw (147 MB tar)
        │   ├── filelist        ← SHA-256 manifest + RSA-2048 detached signature
        │   ├── version.tag     ← "4a965be03a72-26.8.0" (build id)
        │   ├── install/*.sh    ← install.sh, update.sh, download.sh, silent_install.sh,
        │   │                     activate.sh, migrate.sh, check_compat.sh ...
        │   └── HMA VPN.app.tar ← the real 154 MB app bundle
        └── Scripts/postinstall ← moves .raw/.lat into update-data storage, runs
                                  install/install.sh, sends telemetry ("burger v3/v4")
```

- Install target: `/Applications/HMA VPN.app`, payload first staged in
  `/Library/Application Support/HMA VPN/tmpInstall`.
- `postinstall` accepts optional `config.tar` (license/wks/SMB + `EDAT/EREF`,
  `EDAT/GIET` attribution tokens) and `cookie.tag` — used by partner/enterprise
  builds of the same package.
- Telemetry on install: `submit -p lifecycle -m event install` (Burger v3) and
  `submit -p install ...` (Burger v4) with eref/giet attribution.

## 2. App architecture

```
HMA VPN.app/
├── MacOS/HMA VPN                ← menu-bar GUI (LSUIElement), Swift/ObjC,
│                                  NSPrincipalClass = HMAVPN.AntivirusModule
│                                  (built on Avast's shared product platform)
├── XPCServices/
│   ├── com.privax.osx.provpn.api.xpc   ← local API bridge (launchd MachServices),
│   │                                     verifies caller signatures (SignatureCache)
│   └── HideMyAssVPN.app                ← privileged VPN helper daemon
│                                         (launchd KeepAlive, label com.privax.osx.provpn.vpn)
├── PlugIns/  VPN, Services, Preferences, Notifications, IPMStuff frameworks
├── Library/SystemExtensions/
│   └── com.privax.osx.provpn.networkextension.systemextension (v17.9.700)
│       Entitlements: app-proxy-provider, content-filter-provider, dns-proxy
│       Providers: AppProxyProvider (tunnel), DnsProxyProvider, FilterDataProvider
└── Contents/Backend/            ← all privileged plumbing
    ├── hub/                     ← bash "module" init system (init.sh runs
    │   ├── modules/000_update..150_uninstaller.sh   numbered modules on start)
    │   └── usermodules/         ← per-user launch (035_vpn, 040_gui)
    ├── services/                ← root C++ daemons (protobuf-lite, libcurl, libpcap,
    │   │                          CoreWLAN):
    │   ├── com.privax.osx.provpn.service   ← main orchestrator (license, myaccount,
    │   │                                    alpha, submit, cyberhygiene, NOS...)
    │   ├── com.privax.osx.provpn.filter    ← content filter: firewall, kill switch,
    │   │                                    split tunnel, Remote Access Shield
    │   ├── com.privax.osx.provpn.hns       ← Avast Home Network Security
    │   │                                    (WiFi/router/device scan, AvHns* protos)
    │   └── com.privax.osx.provpn.ext       ← NetworkExtension/system-extension loader
    ├── utils/                   ← cmd, cfgctl, cliutils, submit (telemetry),
    │   │                          myaccountcli (account/login/licenses), alphacli,
    │   │                          update-report, ndt7 (M-Lab speed test),
    │   │                          bspatch, openssl, newsyslog,
    │   ├── com.privax.osx.provpn.wireguardtun  ← Go WireGuard engine (zx2c4)
    │   └── com.privax.osx.provpn.mimictun      ← Go WireGuard-over-TLS "Mimic" engine
    ├── defaults/*.dfl           ← encrypted default configs (see §4)
    ├── scripts/update/          ← self-update: shepherd, cacerts, bsdiff pipeline
    └── launch/                  ← LaunchDaemons: init (RunAtLoad), update
                                   (StartInterval=600s, ThrottleInterval=3h)
```

## 3. VPN tunnel technology

Two Go tunnel engines, both userspace (no kernel extension; the SystemExtension
routes packets into them):

1. **wireguardtun** — stock WireGuard (`golang.zx2c4.com/wireguard`):
   `--private-key --peer-pub --endpoint host:51820 --keepalive 25 --allowed 0.0.0.0/0,::/0`,
   plus split-tunnel and `--ifscope` (bind to tunnel interface, ticket NSV-31632).

2. **mimictun** (17 MB) — Avast **"Mimic"** protocol
   (`git.int.avast.com/mimic/mimic-tun`, `mimic-core`): the WireGuard data plane is
   encapsulated in a custom TLS 1.3 tunnel so VPN traffic looks like ordinary HTTPS:
   - multiplexed streams ("weaver"/"looper"), handshake states Greeted → Open,
     PING/PONG keepalive, per-stream flow control, user/pass credentials,
     multi-dialer round-robin, reconnect/"DataOnlyJoin"
   - **Post-quantum key mix-in**: `ApplyPostQuantumMixinAsInitiator`,
     suite `MLKEM1024-P384`, `mimic/pqe-join` (hybrid PQE over TLS)
   - **ECH (Encrypted Client Hello)** support: `-ech-public-key` + `-tlsdomain`
     (outer SNI vs inner SNI), mutually exclusive with legacy pinned-CA mode
   - userspace IP stack = gVisor netstack (`pkg/tcpip/*`), DNS-over-TCP bridge,
     DNS proxy pool, TCP forwarder with slot limiting, download-rate instrumentation
   - IPv6 leak protection: refuses to start if IPv6 black-hole route can't be
     installed ("refusing to start tunnel to avoid IPv6 leak")
   - FIPS 140-3 mode strings; internal IPs 172.16.16.0/24, test IPs 99.192.182.100/101

Server-side discovery: NOS (`_nos._tcp.nos.avast.com` SRV + `config.nos.avast.com`
timeouts), IKEv2 servers at `ikev2.hidemyass.com` (Apple IKEv2Provider whitelisted
in the kill-switch defaults).

## 4. Encrypted default configs — key recovered

`Backend/defaults/*.dfl` are JSON encrypted with a **64-byte repeating XOR key**
(same key for the whole product). Recovered by cryptanalysis:

- all `.dfl` files share an identical 40+ byte prefix → same fixed keystream;
- ciphertext column MSBs are constant with period 64 → keystream period 64,
  plaintext is 7-bit ASCII JSON;
- printable-charset intersection over the 5 files → ≤5 candidates/byte;
- crib `{\n    "general"` pinned the start; beam search + JSON validation
  resolved the rest (hns.dfl is JSONC — it contains comments).

```
KEY (64 bytes, hex):
953df830d12c8b20a83cca7c0c77d1ce938ee15ce36c7bed72e1a56dd1bf6c
4932518bf5b42030063fed4e885d3b01fa4568ed58dc9aac9ae542d97c434c62fe
```

Decrypted files are in `decrypted-configs/`. Highlights:

- **filter.dfl** sections: `general, filterDnsCache, smartvpn, firewall,
  networkmonitor, rasKext, ras, rasBruteforceSsh/Vnc/Samba, killswitch, splittunnel`
  - Kill switch: per-app whitelist by (teamId, bundleId); mimictun/wireguardtun/
    GUI/IKEv2Provider/com.apple.route whitelisted; `allowLocalNetworks=false`.
  - Split tunnel: per-app and per-DNS routing in both directions, macOS
    Software Update bypass list, internal excluded apps.
  - Firewall: mode "smart", popup asks reported to Burger, connection blocker,
    Remote Access Shield brute-force thresholds (SSH: 12/10s, 30/min, 40/h, 60/day
    → block whole IP 1 h).
  - Smart VPN: DNS-decider "dontBlockServices" list (full endpoint inventory).
- **service.dfl** sections: `general, alpha, common, privacy, submit,
  cyberhygiene, nos, myaccount, scan, compat, usbProtection, ipsEnabling,
  leapService, licenseAlphaLeapMigration`
  - privacy defaults: `dataCollectionAllowed=true, productOffersAllowed=true,
    thirdPartyAnalyticsAllowed=true, personalizedDiscountsAllowed=true` (all opt-out).
  - submit: `heartbeatIntervalInSeconds=21600` (6 h heartbeat to analytics).
  - myaccount: `my-mac.ff.avast.com`, `my-devices.ff.avast.com`, pairing enabled.
  - alpha (licensing): `alpha-license-dealer-service.ff.avast.com`,
    `alpha-crap-service.ff.avast.com`, `cebe.norton.com`,
    geoinfo `https://ip-info.ff.avast.com/v2/info`.
  - NOS: `_nos._tcp.nos.avast.com`, `config.nos.avast.com` + fallback timeouts.

## 5. Update / self-upgrade channel

- Config: `UPDATE_URL="https://mac-vpn.u.avcdn.net/mac-vpn-gen/10_13"`,
  `BETA_CHANNEL`, `PROGRAM_UPDATE_ENABLED`, `VPS_UPDATE_ENABLED`.
- Flow (scripts/update/download.sh): poll `$URL/VPNHMA/{VPNHMA.lat, .inf, .ful,
  .dif, .sig}` → chain bspatch deltas from stored `.raw`, or download full `.ful`;
  staged into `/Library/Application Support/HMA VPN/update-data`, applied by
  `install/update.sh`.
- Verification is solid: `filelist` inside the package is signed (RSA-2048,
  pinned public key `install-VPNHMA.pem`), every member checked against the
  signed SHA-256 list, "extra files in archive" rejected; same scheme for
  `cacerts` and `vps9` (Avast definitions-style package, MD5-checked when the
  online installer pre-places it).
- LaunchDaemon runs `update.sh` every 600 s (throttled to 3 h). Shepherd
  (`shepherd.avcdn.net`) delivers remote config as `shepherd.dfl` + AB-test
  headers, merged per-module at runtime.

## 6. Telemetry & network endpoints

Telemetry = Avast **Burger** v3/v4 (`analytics.ff.avast.com`,
`submit.sb.avast.com`, `bugs-bunny.sb.avast.com`): Install/Heartbeat(6 h)/
UserActivity/Uninstall/DataSharingPreferences/RatingFeedback/GenScore vectors,
plus HNS scan reports via Streamback. Crash logs uploaded by
`com.privax.osx.provpn.crashreport` (component install, file attach).

Complete host inventory found in binary strings + decrypted configs:

| Purpose | Hosts |
|---|---|
| Program updates | mac-vpn.u.avcdn.net, mac.sl.u.avcdn.net, shepherd.avcdn.net |
| Accounts/login | my-mac.ff.avast.com, my-devices.ff.avast.com, id.avast.com, id.hidemyass.com, my.hidemyass.com, local.hidemyass.com, auth.ff.avast.com |
| Licensing | alpha-license-dealer(.service).ff.avast.com, alpha-lqs.ff.avast.com, alpha-crap(.service).ff.avast.com, cebe.norton.com, api.se-platform.com, my.avast.com |
| Telemetry | analytics.ff.avast.com, submit.sb.avast.com, bugs-bunny.sb.avast.com, hns.sb.avast.com, viruslab-samples.sb.avast.com |
| IP/location | ip-info.ff.avast.com (also ip-info-test), vpn-sd.ff.avast.com |
| In-product msgs | ipm-provider.ff.avast.com |
| Misc | static.avast.com, id-ffl.avast.com, packet-responder.ff.avast.com |
| VPN data plane | ikev2.hidemyass.com + NOS-discovered Mimic/WG servers |

URL schemes: `hmavpn://`, `hmavpnipm://`. App Transport Security allows
**insecure HTTP** to amionline/ip-info/vpn-sd.ff.avast.com (legacy exception).

## 7. Notable observations

- The kill-switch/split-tunnel engine is a real content-filter SystemExtension
  that gates by code signature (teamId+bundleId), not just paths.
- The whole privileged side is a bash module system (like Avast/AVG products):
  a root `init.sh` LaunchDaemon launches numbered modules; per-user modules
  launch the GUI. The same skeleton as Avast SecureLine/AV.
- `EDAT/ECOO = mmm_hma_998_888_000_m` in config.tar is campaign/affiliate
  attribution data that the installer forwards to the first-run telemetry.
- Local IPC: unix sockets (`activity.sock`, `hns.sock` with peer verification
  disabled by default — see hns.jsonc comment [AVU-9176]), XPC api service
  verifies caller code signatures before answering.
- `com.privax.focus.app` utility — integrates with macOS Focus to silence
  notifications (NSFocusStatusUsageDescription).
- Uninstallers ship both in-app (`utils/com.privax.osx.provpn.uninstaller.app`)
  and as Backend hub scripts (`hub/uninstall*.sh`), incl. `userinit.sh` cleanup.

## 8. Artifacts

Decrypted defaults and vendor scripts are intentionally not committed to this
repository (vendor content). Decryption: XOR with the 64-byte key above,
`plain[i] = cipher[i] ^ key[i mod 64]`.

---

## Addendum (Oct 2026) — live account-plane testing with the local install

Tested against the running HMA install on this machine and the production APIs:

- **Local session material located** (all under `/Library/Application Support/HMA VPN/`):
  plaintext `license.privaxlicdata` (WalletKey + ActiveLicenseId), encrypted
  `license_my.data` (**decrypts with the same 64-byte XOR key from §4**), and
  `state/vpn/` holding the tunnel plane: `tokenCoreSE.json` (base64 device blob:
  JWT from issuer **`elysium`**, aud `SE_GLOBAL_JWT`, scopes
  `passage geo torrent stats discovery onboard offline_access wrangler`; tunnel
  client certificate + `certificatePassword`; gateway hostname pattern
  **`%@.ult.surfeasy.mobi`** — HMA tunnels ride SurfEasy/elysium infra),
  `tokenPSN.json` (= ActiveLicenseId), and mimic session files
  (`mimic.auth/connection/crt` — encrypted with a stronger, machine-bound scheme).
- **License API reproduced in raw Python**: `POST
  https://my-mac.ff.avast.com/v1/query/get-exact-application-licenses` with JSON
  `{"walletKeys":[...]}` + the client's **Vaar-Header-\*** identity envelope
  → HTTP 200 full license JSON. Without Vaar headers: 400 "Cannot parse Vaar
  request". Vaar header set recovered via `myaccountcli --get-vaar-headers`.
- **Live result**: HMA Pro VPN - 1 user, 2 years, PAID, 4/5 device slots used,
  auto-renew, expires 2026-11-30.
- **Activation path** (`alphacli -c CODE [-w wallet]`): license-dealer
  `POST /v2/analyze` → `POST /v2/activate`, protobuf bodies
  (`com.avast.alpha.crap.api.v2.*`); error taxonomy in binary: overused,
  disabled, unsupported type, needs customer info.
- Account commands implemented as `suite/bin/hma_account.py`
  (status / licenses / activate / login). See `suite/docs/ACCOUNTS.md`.

### Addendum 2 — country selection model (verified live)

- The client stores locations as country entries with **`fqdn: <CC>.ult.surfeasy.mobi`**
  (found in `~/Library/Application Support/HMA VPN/conf/vpn.location.conf` and
  `vpn.recents.conf`: IN, CH, JP, GB, AU with `countryName`, `p2pAllowed`,
  `streaming`, `ipShuffle` flags).
- DNS verified live for US/GB/DE/FR/NL/CH/JP/IN/AU/CA (+ more resolve).
- Tunnel ports on the gateways reject plain probes from unauthenticated
  clients (as expected for the Mimic/WG services). VPS tunnels therefore use
  HMA's official per-location OpenVPN configs; country switching = swapping
  the active `<CC>.conf` (implemented as `vps/select-country.sh`).
