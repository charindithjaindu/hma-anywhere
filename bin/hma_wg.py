#!/usr/bin/env python3
"""hma_wg.py — assemble a wg-quick config for HMA WireGuard endpoints.

IMPORTANT (read this): the HMA macOS client negotiates WireGuard per session —
there are no static peer keys in the DMG. To use this generator you need the
*server's* public key and your own provisioned private key from an authorized
HMA session (your account, or your own machine running the official client).
Key generation here only creates YOUR side of a NEW keypair to hand to
whatever provisioning path you use.

Usage:
  # 1) create a fresh client keypair (X25519, RFC 7748 — stdlib-only):
  python3 hma_wg.py --gen-keypair

  # 2) build the config once you have all pieces:
  python3 hma_wg.py --endpoint WG-HOST:51820 \
      --peer-pub <SERVER_PUBLIC_KEY_B64> \
      --client-priv <YOUR_PRIVATE_KEY_B64> \
      --address 10.x.x.x/32 [--dns 1.1.1.1] [--firewall] [--out wg0.conf]

  --firewall adds PostUp/PostDown rules that block all traffic outside the
  tunnel (kill-switch semantics, equivalent to the client's killswitch.dfl).
"""
import argparse
import base64
import binascii
import os
import sys

# ------------------------------------------------------------- X25519 (7748)
P = 2**255 - 19
A24 = 121665

def _x25519(k_bytes, u_bytes):
    def _clamp(k):
        k = bytearray(k)
        k[0] &= 248
        k[31] &= 127
        k[31] |= 64
        return bytes(k)
    k = int.from_bytes(_clamp(k_bytes), "little")
    # RFC 7748: mask the most significant bit of the decoded coordinate
    x1 = int.from_bytes(u_bytes, "little") & ((1 << 255) - 1)
    x2, z2, x3, z3 = 1, 0, x1, 1
    swap = 0
    for t in range(254, -1, -1):
        k_t = (k >> t) & 1
        swap ^= k_t
        if swap:
            x2, x3, z2, z3 = x3, x2, z3, z2
        swap = k_t
        a = (x2 + z2) % P
        aa = a * a % P
        b = (x2 - z2) % P
        bb = b * b % P
        e = (aa - bb) % P
        c = (x3 + z3) % P
        d = (x3 - z3) % P
        da = d * a % P
        cb = c * b % P
        x3 = (da + cb) ** 2 % P
        z3 = x1 * (da - cb) ** 2 % P
        x2 = aa * bb % P
        z2 = e * (aa + A24 * e) % P
    if swap:
        x2, x3, z2, z3 = x3, x2, z3, z2
    res = x2 * pow(z2, P - 2, P) % P
    return res.to_bytes(32, "little")

def x25519_public(private: bytes) -> bytes:
    return _x25519(private, (9).to_bytes(32, "little"))

# ----------------------------------------------------------------- key utils

def b32kebab(b: bytes) -> str:
    return base64.b64encode(b).decode()

def parse_wg_key(s, what):
    s = s.strip()
    try:
        raw = base64.b64decode(s, validate=True)
    except (binascii.Error, ValueError):
        raise SystemExit("error: %s is not valid base64" % what)
    if len(raw) != 32:
        raise SystemExit("error: %s must decode to 32 bytes (got %d)" % (what, len(raw)))
    return raw

def parse_endpoint(s):
    if ":" not in s:
        raise SystemExit("error: --endpoint must be host:port")
    host, _, port = s.rpartition(":")
    if not host or not port.isdigit():
        raise SystemExit("error: --endpoint must be host:port")
    return host, int(port)

# ----------------------------------------------------------------- generator

FIREWALL_RULES = """# kill-switch: only the tunnel interface may leave (see filter.dfl killswitch)
PostUp = iptables -I OUTPUT ! -o %i -m mark ! --mark $(wg show %i fwmark) -j REJECT; ip6tables -I OUTPUT ! -o %i -m mark ! --mark $(wg show %i fwmark) -j REJECT
PreUp = ip rule add fwmark $(wg show %i fwmark) table 51820 >/dev/null 2>&1 || true
PreUp = ip route add table 51820 default dev %i >/dev/null 2>&1 || true
PostDown = iptables -D OUTPUT ! -o %i -m mark ! --mark $(wg show %i fwmark) -j REJECT; ip6tables -D OUTPUT ! -o %i -m mark ! --mark $(wg show %i fwmark) -j REJECT; ip rule del table 51820 2>/dev/null || true; ip route del table 51820 2>/dev/null || true
"""

TEMPLATE = """[Interface]
PrivateKey = {client_priv}
Address = {address}
DNS = {dns}
{firewall}
[Peer]
PublicKey = {peer_pub}
AllowedIPs = {allowed_ips}
Endpoint = {endpoint}
PersistentKeepalive = {keepalive}
{extra}
"""

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gen-keypair", action="store_true",
                    help="generate a fresh X25519 keypair and exit")
    ap.add_argument("--endpoint", help="WG server, host:port (e.g. srv:51820)")
    ap.add_argument("--peer-pub", help="server WireGuard public key (base64)")
    ap.add_argument("--client-priv", help="your WireGuard private key (base64)")
    ap.add_argument("--address", default="10.8.0.2/32",
                    help="your tunnel address/CIDR (from provisioning)")
    ap.add_argument("--dns", default="1.1.1.1,1.0.0.1")
    ap.add_argument("--allowed-ips", default="0.0.0.0/0, ::/0",
                    help="traffic routed into the tunnel")
    ap.add_argument("--keepalive", default="25")
    ap.add_argument("--mtu", help="optional MTU (try 1420 if issues)")
    ap.add_argument("--firewall", action="store_true",
                    help="add kill-switch PostUp/PostDown rules (Linux)")
    ap.add_argument("--preshared", help="optional preshared key (base64)")
    ap.add_argument("--out", default="wg0.conf")
    args = ap.parse_args()

    if args.gen_keypair:
        priv = os.urandom(32)
        pub = x25519_public(priv)
        print("PrivateKey = %s" % b32kebab(priv))
        print("PublicKey  = %s   # <-- provision/replace your old pubkey with this" % b32kebab(pub))
        print("(created locally, never transmitted by this tool)")
        return 0

    missing = [f for f in ("--endpoint", "--peer-pub", "--client-priv")
               if not getattr(args, f.lstrip("-").replace("-", "_"))]
    if missing:
        raise SystemExit("error: missing required options: %s (or use --gen-keypair)" %
                         ", ".join(missing))

    host, port = parse_endpoint(args.endpoint)
    parse_wg_key(args.peer_pub, "peer public key")
    parse_wg_key(args.client_priv, "client private key")

    extra = ""
    if args.mtu:
        extra = "MTU = %s\n" % args.mtu
    if args.preshared:
        parse_wg_key(args.preshared, "preshared key")
        extra += "PresharedKey = %s\n" % args.preshared.strip()

    conf = TEMPLATE.format(
        client_priv=args.client_priv.strip(),
        address=args.address,
        dns=args.dns,
        firewall=FIREWALL_RULES + "\n" if args.firewall else "",
        peer_pub=args.peer_pub.strip(),
        allowed_ips=args.allowed_ips,
        endpoint="%s:%d" % (host, port),
        keepalive=args.keepalive,
        extra=extra,
    )
    with open(args.out, "w") as fh:
        fh.write(conf)
    os.chmod(args.out, 0o600)
    print("wrote %s (mode 0600)" % args.out)
    print("bring it up with:  sudo wg-quick up %s" %
          os.path.basename(args.out).replace(".conf", ""))
    return 0

if __name__ == "__main__":
    sys.exit(main())
