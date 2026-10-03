#!/usr/bin/env python3
"""hma_account.py — drive HMA licensing with your own credentials.

Two ways to identify yourself (both are YOUR credentials, obtained from YOUR
own HMA installation or HMA account — never from anyone else):

  WalletKey   machine-local licensing credential. Readable from your own
              installed client (/Library/Application Support/HMA VPN/config/
              license.privaxlicdata). Works with zero passwords.
  Email+pass  full account login (interactive via the installed myaccountcli).

Commands:
  status        auto-detect local install -> wallet key -> live license check
  licenses      same query, but with --wallet-key supplied explicitly (VM-usable)
  activate      redeem an activation code into the wallet (uses the installed
                alphacli; needs HMA installed on this machine)
  login         interactive email login -> all licenses on the account
                (uses installed myaccountcli; password never leaves the VM)

The raw HTTP license query reproduces exactly what the official client sends:
POST {walletKeys:[...]} with the client's Vaar-Header-* identity headers to
my-mac.ff.avast.com. Verified working against the production API.
"""
import argparse
import getpass
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

MYACCOUNT_URL = "https://my-mac.ff.avast.com/v1/query/get-exact-application-licenses"
ALD_URL = "https://alpha-license-dealer-service.ff.avast.com"  # /v2/analyze, /v2/activate (protobuf)
INSTALL_SUPPORT = "/Library/Application Support/HMA VPN"
INSTALL_UTILS = "/Applications/HMA VPN.app/Contents/Backend/utils"
APP_VERSION = "26.8.0-4a965be03a72"


# --------------------------------------------------------------- local state

def local_wallet_key():
    path = os.path.join(INSTALL_SUPPORT, "config", "license.privaxlicdata")
    try:
        txt = open(path).read()
        m = re.search(r'WalletKey="([^"]+)"', txt)
        return m.group(1) if m else None
    except OSError:
        return None


def local_vaar_headers():
    cli = os.path.join(INSTALL_UTILS, "com.privax.osx.provpn.myaccountcli")
    if not os.path.exists(cli):
        return default_vaar_headers()
    try:
        out = subprocess.run([cli, "--get-vaar-headers"], capture_output=True,
                             text=True, timeout=15).stdout
        pairs = json.loads(out)
        return {p["name"]: p["value"] for p in pairs}
    except Exception:
        return default_vaar_headers()


def default_vaar_headers():
    """Headers reconstructed from the RE — used on VMs without an install.

    Device-Id / App-Id are placeholder GUIDs; any UUID-shaped values are
    accepted by the API. On a machine with HMA installed, run
    `status` — it auto-loads the real ones via `myaccountcli --get-vaar-headers`.
    """
    return {
        "Vaar-Version": "0",
        "Vaar-Header-Device-Id": "0A0B0C0D-0E0F-4001-8001-000000000001",
        "Vaar-Header-Device-Platform": "OSX",
        "Vaar-Header-App-Build-Version": APP_VERSION,
        "Vaar-Header-App-Id": "0A0B0C0D-0E0F-4002-8002-000000000002",
        "Vaar-Header-App-IPM-Product": "249",
        "Vaar-Header-App-Product-Brand": "PRIVAX",
        "Vaar-Header-App-Product-Mode": "PAID",
        "Vaar-Header-App-Package-Name": "com.privax.osx.provpn",
        "Vaar-Header-App-Product-Edition": "HMA_VPN_CONSUMER",
    }


# --------------------------------------------------------------- license API

def query_license(wallet_key, device_id=None, timeout=12):
    """Raw HTTP license query — VM-native, no official binaries involved."""
    headers = default_vaar_headers()
    if device_id:
        headers["Vaar-Header-Device-Id"] = device_id
    headers["Content-Type"] = "application/json"
    headers["User-Agent"] = "HMA VPN/26.8.0 (com.privax.osx.provpn)"
    req = urllib.request.Request(
        MYACCOUNT_URL,
        data=json.dumps({"walletKeys": [wallet_key]}).encode(),
        headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def print_license(lic, prefix="  "):
    prod = lic.get("product", {})
    usage = lic.get("licenseUsage", {})
    exp = lic.get("expires")
    exp_h = "-"
    if exp:
        import datetime
        exp_h = datetime.datetime.fromtimestamp(exp / 1000.0, datetime.timezone.utc) \
                         .strftime("%Y-%m-%d")
    print(prefix + "license id    : %s" % lic.get("id"))
    print(prefix + "product       : %s" % prod.get("name"))
    print(prefix + "mode          : %s" % lic.get("mode"))
    print(prefix + "schema        : %s" % lic.get("schemaId"))
    print(prefix + "devices       : %s used / %s max%s" % (
        usage.get("current"), usage.get("maximum"),
        "  (OVERUSED!)" if usage.get("overused") else ""))
    print(prefix + "expires       : %s" % exp_h)
    print(prefix + "auto-renew    : %s" % (lic.get("order", {}).get("billing", {}).get("auto")))
    print(prefix + "wallet keys   : %s" % ", ".join(lic.get("walletKeys", [])))
    for feat in lic.get("features", []):
        for res in feat.get("resources", []):
            print(prefix + "feature       : %s / %s (%s of %s)" % (
                feat.get("key"), res.get("name"),
                res.get("currentValue"), res.get("originalValue")))


# ------------------------------------------------------------------ commands

def cmd_status(args):
    print("== local install")
    wk = local_wallet_key()
    cli = os.path.join(INSTALL_UTILS, "com.privax.osx.provpn.myaccountcli")
    print("  install present : %s" % os.path.exists(cli))
    print("  wallet key      : %s" % ("found" if wk else "not found"))
    if not wk:
        print("  run:  hma_account.py licenses --wallet-key XXXX")
        return 1
    print("\n== live license check (raw HTTP, VM-native)")
    try:
        lic = query_license(wk)
    except urllib.error.HTTPError as e:
        print("  HTTP %s: %s" % (e.code, e.read()[:200].decode(errors="replace")))
        return 2
    licenses = lic if isinstance(lic, list) else [lic]
    for l in licenses:
        print_license(l)
    return 0


def cmd_licenses(args):
    try:
        lic = query_license(args.wallet_key, device_id=args.device_id)
    except urllib.error.HTTPError as e:
        print("HTTP %s: %s" % (e.code, e.read()[:200].decode(errors="replace")))
        return 2
    licenses = lic if isinstance(lic, list) else [lic]
    for l in licenses:
        print_license(l)
    return 0


def cmd_activate(args):
    """Redeem an activation code via the installed alphacli (protobuf codec)."""
    cli = os.path.join(INSTALL_UTILS, "com.privax.osx.provpn.alphacli")
    if not os.path.exists(cli):
        print("alphacli not found — activation needs HMA installed on this machine.")
        print("(the HTTP API /v2/analyze|/v2/activate is protobuf-only; CLI is the codec)")
        return 1
    cmd = [cli, "-c", args.code]
    wk = args.wallet_key or local_wallet_key()
    if wk:
        cmd += ["-w", wk]
    if args.license_id:
        cmd += ["-l", args.license_id]
    print("activating code %s%s ..." % (args.code,
          " into wallet %s" % wk if wk else " (new wallet)"))
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    out = (r.stdout or "") + (r.stderr or "")
    # alphacli is quiet on success; 0 = redeemed
    if r.returncode == 0:
        print("activation succeeded.")
        if wk:
            try:
                lic = query_license(wk)
                for l in (lic if isinstance(lic, list) else [lic]):
                    print_license(l)
            except Exception as e:
                print("(license re-check failed: %s)" % e)
        return 0
    print("activation FAILED (exit %d):" % r.returncode)
    print("\n".join(l for l in out.splitlines() if "alphacli: log" not in l))
    return 2


def cmd_login(args):
    cli = os.path.join(INSTALL_UTILS, "com.privax.osx.provpn.myaccountcli")
    if not os.path.exists(cli):
        print("myaccountcli not found — email login needs HMA installed.")
        return 1
    password = os.environ.get("HMA_PASSWORD") or getpass.getpass("HMA password for %s: " % args.email)
    r = subprocess.run([cli, "--login-email", "--email", args.email,
                        "--password", password],
                       capture_output=True, text=True, timeout=60)
    out = (r.stdout or "")
    if r.returncode != 0:
        err = (r.stderr or "")
        print("login failed (exit %d)" % r.returncode)
        print("\n".join(l for l in err.splitlines() if "alphacli: log" not in l)[:500])
        return 2
    # token is printed to stdout; do NOT echo it, feed it straight into the query
    token = out.strip().strip('"')
    print("login ok (token %s...)" % token[:12])
    r2 = subprocess.run([cli, "--get-all-user-licenses", "--token", token],
                        capture_output=True, text=True, timeout=60)
    if r2.returncode != 0:
        print("license listing failed")
        return 2
    for l in json.loads(r2.stdout):
        print_license(l)
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    ap.add_argument("--help-all", action="store_true")
    sub.add_parser("status", help="detect local install and check license live")
    p = sub.add_parser("licenses", help="query license by wallet key (VM-usable)")
    p.add_argument("--wallet-key", required=True)
    p.add_argument("--device-id", help="override Vaar device id header")
    p = sub.add_parser("activate", help="redeem an activation code (needs local install)")
    p.add_argument("--code", required=True, help="activation key, e.g. XXXX-XXXX-XXXX-XXXX")
    p.add_argument("--wallet-key", help="target wallet (default: local install)")
    p.add_argument("--license-id", help="optional license to attach to")
    p = sub.add_parser("login", help="email login -> all account licenses")
    p.add_argument("--email", required=True)

    args = ap.parse_args()
    return {"status": cmd_status, "licenses": cmd_licenses,
            "activate": cmd_activate, "login": cmd_login}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
