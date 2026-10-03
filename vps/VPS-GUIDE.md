# HMA-as-a-proxy on a VPS — for apps running on the VM, with country selection

Goal: apps on your VPS point their proxy settings at **localhost ports**; that
traffic exits through an HMA tunnel in the **country you choose**.

```
apps on VPS ──▶ 127.0.0.1:1080 (SOCKS5, dante)  ──▶ tun0 ──▶ <CC>.ult.surfeasy.mobi
            ──▶ 127.0.0.1:8888 (HTTP,  tinyproxy) ──┘        (HMA egress IP)
                              ▲
              select-country.sh DE   ← switch countries anytime
```

Facts established from the RE (verified live):
- HMA's gateways follow the pattern **`<CC>.ult.surfeasy.mobi`** — the client
  itself stores locations as `IN`/`CH`/`JP`/`GB`/`AU` + `.ult.surfeasy.mobi`;
  DNS resolves for US/DE/FR/NL/CA/SG and more.
- The tunnel protocol/auth on those gateways is HMA-proprietary (Mimic) —
  the sanctioned way to drive them from Linux is **HMA's official per-location
  OpenVPN configs** (your account's manual-setup/router section). One config
  per country = the basis of country switching below.
- Your license has 1 free device slot (4/5 used); the VPS takes it.

## 1. Install country configs

From your HMA account, download the per-location OpenVPN configs for the
countries you want, put them on the VPS renamed by country code:

```
/etc/openvpn/hma/US.conf
/etc/openvpn/hma/GB.conf
/etc/openvpn/hma/DE.conf
...
```

Then create the credentials file once (HMA manual-setup credentials):

```bash
sudo sh -c 'printf "YOUR_HMA_LOGIN\nYOUR_HMA_PASSWORD\n" > /etc/openvpn/hma/hma.creds && chmod 600 /etc/openvpn/hma/hma.creds'
```

## 2. SSH survival — run BEFORE the first tunnel

```bash
sudo ./setup-netrules.sh            # keep SSH alive under full tunnel
sudo ./setup-netrules.sh --failclose   # optional: drop egress when tunnel down
```

## 3. Bring up the first country

```bash
sudo ./select-country.sh --list     # shows installed countries
sudo ./select-country.sh US         # symlink + restart openvpn-client@hma
./check-egress.sh                   # confirm the egress is US
```

## 4. The proxies (install once, survives country switches)

```bash
sudo ./setup-proxy.sh --http 8888
```

- **SOCKS5**: `127.0.0.1:1080` (user `danteproxy`, password you chose)
- **HTTP**: `127.0.0.1:8888` (tinyproxy chained through dante)

dante's `external:` is pinned to the tunnel interface — if the tunnel is down,
proxied connections fail **closed** (no leak of the VPS IP). Both proxies keep
running across `select-country.sh` switches; only the egress country changes.

## 5. Point your apps at it

```bash
export http_proxy=http://danteproxy:PASS@127.0.0.1:8888
export https_proxy=$http_proxy
# or per-app:  curl -x socks5h://danteproxy:PASS@127.0.0.1:1080 https://example.com
```

- `socks5h://` (or tinyproxy for plain HTTP apps) sends DNS through the tunnel
  as well — same DNS behavior as the HMA client.
- Python: `requests` honors the env vars; `aiohttp`/`httpx` take per-request
  proxies. Node: `--proxy-server` or a tiny agent. Docker containers on the VM:
  use the VM's IP instead of 127.0.0.1 (dante listens on loopback; add a second
  `internal:` line if needed — see Troubleshooting).

## 6. Switch countries anytime

```bash
sudo ./select-country.sh JP         # tunnel reconnects to Japan (~3-5 s)
./check-egress.sh                   # apps now egress via JP
sudo ./select-country.sh current    # what country am I on?
```

The proxies don't restart; established app connections drop on switch and
reconnect via the new country.

## Troubleshooting

| Symptom | Fix |
|---|---|
| SSH died | run `setup-netrules.sh` from provider console; `ip rule show` |
| `select-country.sh` exits 2 | `journalctl -u openvpn-client@hma -n 30` — usually auth or provider blocking; try port-443 config variant from HMA |
| Proxy returns errors after switch | tunnel didn't come up (fail-close doing its job); check journal, rerun select-country |
| Apps in Docker can't reach 127.0.0.1 | add `internal: 172.17.0.1 port = 1080` (docker0) + matching `client pass`/`socks pass` blocks in `/etc/danted.conf`, `systemctl restart danted` |
| Wrong country shows | OpenVPN config pinned a specific server — check the `remote` line in the `<CC>.conf`; configs for whole countries list several (keep `remote-random`) |
| DNS leaks | ensure apps use `socks5h` / the HTTP proxy (not direct DNS); optional: `aptive-dns` script in OpenVPN config |
