# HMA account & licensing — tested flows

Everything here was validated live against production (Oct 2026) using the
wallet key of the local HMA install. Principles: only YOUR OWN credentials,
entered/stored on YOUR machine, never pasted into chats; read-only queries by
default; activation only redeems keys you legitimately own.

## Credential types (what the client actually holds)

| Credential | Where (local install) | Purpose |
|---|---|---|
| `WalletKey` (e.g. `XXXXXX-XXXXXX-XXXXXX`) | `/Library/Application Support/HMA VPN/config/license.privaxlicdata` (plaintext) | licensing identity — queries, activation, pairing |
| `ActiveLicenseId` | same file | license to attach actions to |
| JWT access token (issuer `elysium`, aud `SE_GLOBAL_JWT`, scopes incl. `discovery geo passage`) | `state/vpn/tokenCoreSE.json` → `DeviceManager.device` (base64 JSON) | tunnel-plane APIs (12 h lifetime + refresh token) |
| Tunnel client cert + `certificatePassword` + `password` | same blob + `state/vpn/mimic.crt/.auth` (encrypted at rest) | TLS client-auth to gateways |
| Gateway hostname pattern | same blob: `%@.ult.surfeasy.mobi` | per-location VPN endpoints (HMA tunnels ride SurfEasy/elysium infra) |

The licensing plane (wallet key + Vaar headers) is fully usable externally
today. The tunnel plane (elysium `discovery`) needs the client-cert handshake
and is documented as the next layer, not yet implemented.

## Vaar headers (the identity envelope)

Every account/licensing call carries these (recovered from `myaccountcli`;
reproduce with `hma_account.py` automatically):

```
Vaar-Version: 0
Vaar-Header-Device-Id: <UUID>
Vaar-Header-Device-Platform: OSX
Vaar-Header-App-Build-Version: 26.8.0-4a965be03a72
Vaar-Header-App-Id: <UUID>
Vaar-Header-App-IPM-Product: 249
Vaar-Header-App-Product-Brand: PRIVAX
Vaar-Header-App-Product-Mode: PAID
Vaar-Header-App-Package-Name: com.privax.osx.provpn
Vaar-Header-App-Product-Edition: HMA_VPN_CONSUMER
```

## Tested endpoints

| Endpoint | Body | Result |
|---|---|---|
| `POST my-mac.ff.avast.com/v1/query/get-exact-application-licenses` | JSON `{"walletKeys":["..."]}` + Vaar headers | **HTTP 200, full license JSON** (raw Python works) |
| same, without Vaar headers | JSON | 400 "Cannot parse Vaar request" |
| `POST alpha-license-dealer-service.ff.avast.com/v2/analyze` `/v2/activate` | protobuf (`com.avast.alpha.crap.api.v2.*`) | protobuf-only — use installed `alphacli` as codec |

Other known endpoints (from binary strings, not exercised): `/v1/command/
create-account|logout|pair/account-device|pair/account-subscription|
resend-registration-email`, `/v1/query/get-account-by-ticket`,
`/v1/query/get-all-user-licenses` (auth-token), ALD `/api/connect_tokens/_migration`.

## Commands

```bash
# auto-detect local install -> live license status (tested, works)
python3 bin/hma_account.py status

# VM-native: query any wallet key you own (no official binaries needed)
python3 bin/hma_account.py licenses --wallet-key XXXXXX-XXXXXX-XXXXXX

# redeem an activation key into your wallet (wraps installed alphacli)
python3 bin/hma_account.py activate --code XXXXX-XXXXX-XXXXX-XXXXX

# full account login -> all licenses (interactive password, via myaccountcli)
python3 bin/hma_account.py login --email you@example.com
```

## Activation flow (what happens with your key)

`alphacli -c CODE [-w wallet]` internally: `POST /v2/analyze` (classifies the
code: wallet-key-like / needs consumer info / business info / overused /
disabled) → `POST /v2/activate` (redeems into the wallet). Exit 0 = redeemed;
the tool then re-queries the license so you see the new state. Common failure
codes seen in the binary: overuse, disabled code, unsupported code type.

## What a full VM tunnel client still needs

1. **Gateway list**: elysium "discovery" scope API, authenticated by the device
   client cert (`mimic.crt` + `certificatePassword`) — hostname pattern
   `<loc>.ult.surfeasy.mobi`.
2. **Tunnel protocol**: Mimic (WireGuard-over-PQ-TLS) or the IKEv2/WG paths in
   `PROTOCOLS.md` once you have a gateway that speaks them.
3. **Device slots**: license shows `4/5 used` — one more slot exists; pairing a
   new device uses `POST /v1/command/pair/account-device` (ticket + license-id).
