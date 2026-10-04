# Getting started — from an activation key to working proxies

This is the complete path. Time cost: about 10 minutes, of which two steps
(~4 minutes) are on HMA's website because they live behind HMA's own login.

```
Step 1  activate your subscription      (once, browser or one command)
Step 2  download country configs        (once, HMA dashboard)
Step 3  bootstrap your VM               (one command, everything automated)
Step 4  point your apps at localhost    (done — forever)
Step 5  daily driving                   (country switch / rotate / verify)
```

## What you need

- A VPS or VM running **Debian or Ubuntu** with SSH access and root (`sudo`).
- An HMA subscription — if all you have is an **activation key**, Step 1
  turns it into a working subscription.
- Note: the VM consumes one of your device slots (HMA allows 5 by default).
  If all slots are taken, remove an old device in your HMA account first.

---

## Step 1 — Activate your subscription

Pick whichever is easier:

**Option A — in a browser (nothing to install):**
1. Go to [my.hma.com](https://my.hma.com) and log in (or create an account —
   you'll set the email + password that the VM will use later).
2. Find **redeem / activate code** in your account and enter your key.

**Option B — one command, on a machine that has the HMA app installed
(e.g. your Mac):**
```bash
git clone https://github.com/charindithjaindu/hma-anywhere.git
cd hma-anywhere
python3 bin/hma_account.py activate --code XXXXX-XXXXX-XXXXX-XXXXX
```

Verify it worked (optionally, from anywhere):
```bash
python3 bin/hma_account.py licenses --wallet-key YOUR-WALLET-KEY
# don't know your wallet key? on a machine with the HMA app:
python3 bin/hma_account.py status
```

**Why can't the VM redeem the code itself?** HMA's redemption API only
accepts a proprietary protobuf body (verified — JSON gets rejected), which
requires the vendor's own client library. It's a one-time step; after this
the VM never needs the key again.

## Step 2 — Download the country configs

Log into your HMA account's dashboard and find the manual setup / router
configuration section. Download the OpenVPN configs for the countries you
want. On the VM, place them renamed by two-letter country code:

```bash
sudo mkdir -p /etc/openvpn/hma
# upload US.conf, GB.conf, DE.conf, JP.conf ... (rename from HMA's .ovpn names)
```

Also create the credentials file the tunnel will authenticate with —
this is your **HMA account login** from Step 1:

```bash
sudo sh -c 'printf "YOUR_HMA_EMAIL\nYOUR_HMA_PASSWORD\n" > /etc/openvpn/hma/hma.creds && chmod 600 /etc/openvpn/hma/hma.creds'
```

> Why can't the suite download the configs? They sit behind HMA's dashboard
> login. The suite doesn't scrape authenticated web portals — this is the
> official, sanctioned way to obtain them.

## Step 3 — Bootstrap the VM

```bash
git clone https://github.com/charindithjaindu/hma-anywhere.git
cd hma-anywhere/vps
sudo ./bootstrap.sh --countries US,GB
```

That single command (safe to re-run; it resumes where it left off):

1. installs `openvpn`, `dante-server`, `tinyproxy`, `curl`
2. installs **SSH-survival routing** — your SSH session keeps working even
   though the VPN takes over the default route
3. verifies your license (pass `--wallet-key ...` for a live check)
4. brings up the tunnel to the first country (`US`)
5. installs the proxies:
   - **SOCKS5** on `127.0.0.1:1080`
   - **HTTP** on `127.0.0.1:8888`
6. arms a **systemd watchdog** that restarts the tunnel/proxies if they die
   (checked every 2 minutes)

Everything is a systemd service — it survives reboots:

| Service | Role |
|---|---|
| `openvpn-client@hma` | the tunnel (current country) |
| `danted` | SOCKS5 proxy |
| `tinyproxy` | HTTP proxy |
| `hma-watchdog.timer` | auto-heal |
| `hma-netrules` | SSH survival rules |

The proxy password is auto-generated and printed at the end (or set your own
with `--proxy-pass`). Save it.

**Safety net:** if your SSH session ever dies despite the rules, use your VPS
provider's console access and run `ip rule del from <VPS_IP> lookup 200`.
That's why you should test with console access available the first time.

## Step 4 — Point your apps at the proxies

Your apps run on the same VM, so it's just localhost:

```bash
# shell environments
export http_proxy=http://danteproxy:PASSWORD@127.0.0.1:8888
export https_proxy=$http_proxy

# or explicit SOCKS5 (recommended — DNS goes through the tunnel too):
curl -x socks5h://danteproxy:PASSWORD@127.0.0.1:1080 https://example.com
```

| App type | Setting |
|---|---|
| curl, wget, pip, apt | `http_proxy` / `https_proxy` env vars |
| Python `requests` / `httpx` | honor the env vars automatically |
| Browsers / Playwright / Puppeteer | SOCKS5 `127.0.0.1:1080` or HTTP `127.0.0.1:8888` |
| Node apps | `--proxy-server` flag or per-request agent |
| Docker containers on this VM | use the VM's LAN IP instead of 127.0.0.1 — see [Troubleshooting](TROUBLESHOOTING.md#apps-in-docker-cant-reach-127001) |

Prove it works:

```bash
./check-egress.sh
# shows the IP/country seen through the proxy vs the VPS's own IP — they differ
```

## Step 5 — Daily driving

```bash
sudo ./select-country.sh JP     # egress moves to Japan (~5 s)
sudo ./rotate.sh                # new exit IP in the SAME country
./select-country.sh current     # where am I right now?
./select-country.sh --list      # which countries are installed?
```

- Switching country or rotating **does not restart the proxies** — your apps
  just continue through the new egress (established connections drop and
  reconnect automatically).
- `rotate.sh` verifies the IP actually changed (up to 3 attempts) and warns
  if the gateway pins your IP.
- The **fail-closed guarantee**: the proxies are bound to the tunnel
  interface. If the tunnel is down, proxied connections *error out* — your
  apps can never silently fall back to the VPS's real IP.
- The **watchdog** brings the tunnel back within ~2 minutes if anything dies.

---

## Where to next

- Different tunnel technology (IKEv2, WireGuard) → [Tools reference](TOOLS.md)
- What all the scripts actually do → [VPS guide](../vps/VPS-GUIDE.md)
- How HMA's licensing and gateways work under the hood →
  [Accounts & licensing](ACCOUNTS.md), [RE report](RE-REPORT.md)
- Something broke → [Troubleshooting](TROUBLESHOOTING.md)
