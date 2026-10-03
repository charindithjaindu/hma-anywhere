#!/usr/bin/env python3
"""hma_discover.py — discover HMA/Gen Digital VPN infrastructure without credentials.

Reimplements the unauthenticated discovery steps the HMA macOS client performs
at startup (see ../docs/PROTOCOLS.md):

  1. NOS bootstrap   — SRV lookup of _nos._tcp.nos.avast.com (backend gateways)
  2. Geo check       — GET https://ip-info.ff.avast.com/v2/info (no auth)
  3. Static hosts    — update/CDN/licensing/telemetry hosts found in the client
  4. TCP probes      — reachability check of resolved hosts

Everything is the same unauthenticated traffic the official client emits.
Requires only Python 3.8+ stdlib.

Usage:
  python3 hma_discover.py                 # human-readable report
  python3 hma_discover.py --json out.json # machine-readable output
  python3 hma_discover.py --no-probe      # DNS/HTTP only, no TCP probes
"""
import argparse
import json
import random
import socket
import struct
import sys
import urllib.request
import urllib.error

# ---------------------------------------------------------------- DNS client
# Minimal DNS over UDP (A/AAAA/SRV) so the tool has zero dependencies.

QTYPE_A, QTYPE_AAAA, QTYPE_SRV = 1, 28, 33

def _resolv_servers():
    servers = []
    try:
        with open("/etc/resolv.conf") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) >= 2 and parts[0] == "nameserver":
                    servers.append(parts[1])
    except OSError:
        pass
    return servers or ["1.1.1.1", "8.8.8.8"]

def _encode_qname(name):
    out = b""
    for label in name.rstrip(".").split("."):
        raw = label.encode()
        if not 1 <= len(raw) <= 63:
            raise ValueError("bad label in %r" % name)
        out += bytes([len(raw)]) + raw
    return out + b"\x00"

def dns_query(name, qtype, timeout=4.0, server=None):
    """Return list of answers. SRV -> (prio, weight, port, target); A/AAAA -> str."""
    txid = random.getrandbits(16)
    header = struct.pack(">HHHHHH", txid, 0x0100, 1, 0, 0, 0)
    question = _encode_qname(name) + struct.pack(">HH", qtype, 1)  # class IN
    pkt = header + question
    srv = server or random.choice(_resolv_servers())
    af = socket.AF_INET6 if ":" in srv else socket.AF_INET
    s = socket.socket(af, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        s.sendto(pkt, (srv, 53))
        data, _ = s.recvfrom(4096)
    finally:
        s.close()
    if len(data) < 12 or struct.unpack(">H", data[:2])[0] != txid:
        return []
    qd, an = struct.unpack(">HH", data[4:8])
    off = 12

    def skip_name(off):
        while True:
            l = data[off]
            if l == 0:
                return off + 1
            if l & 0xC0 == 0xC0:
                return off + 2
            off += 1 + l

    for _ in range(qd):
        off = skip_name(off) + 4
    results = []
    for _ in range(an):
        off = skip_name(off)
        rtype, _rclass, _ttl, rdlen = struct.unpack(">HHIH", data[off:off + 10])
        off += 10
        rd = data[off:off + rdlen]
        if rtype == QTYPE_A and rdlen == 4:
            results.append(socket.inet_ntop(socket.AF_INET, rd))
        elif rtype == QTYPE_AAAA and rdlen == 16:
            results.append(socket.inet_ntop(socket.AF_INET6, rd))
        elif rtype == QTYPE_SRV and rdlen >= 7:
            prio, weight, port = struct.unpack(">HHH", rd[:6])
            # target may be compressed; decode leniently
            tgt, _ = _decode_name(rd, 6, data)
            results.append((prio, weight, port, tgt))
        off += rdlen
    return results

def _decode_name(buf, off, msg):
    labels, jumped = [], False
    end = off
    seen = 0
    while True:
        if seen > 64:
            break
        l = buf[end]
        if l == 0:
            if not jumped:
                end += 1
            break
        if l & 0xC0 == 0xC0:
            ptr = struct.unpack(">H", buf[end:end + 2])[0] & 0x3FFF
            if not jumped:
                end += 2
            jumped = True
            end_ptr = end  # noqa: F841
            end = ptr
            seen += 1
            continue
        labels.append(buf[end + 1:end + 1 + l].decode("ascii", "replace"))
        end += 1 + l
        seen += 1
    return ".".join(labels) or ".", end

# ---------------------------------------------------------------- host table
# Everything below was extracted from hma_vpn_online.dmg (HMA VPN 26.8.0):
# Backend/defaults/*.dfl (decrypted), binaries, and installer scripts.

STATIC_HOSTS = {
    "update-cdn":     ["mac-vpn.u.avcdn.net"],
    "license-cdn":    ["mac.sl.u.avcdn.net"],
    "remote-config":  ["shepherd.avcdn.net"],
    "nos-gateway":    ["nos.lops.akadns.net"],
    "geo-ip":         ["ip-info.ff.avast.com"],
    "accounts":       ["my-mac.ff.avast.com", "my-devices.ff.avast.com",
                        "id.avast.com", "id.hidemyass.com"],
    "licensing":      ["alpha-license-dealer-service.ff.avast.com",
                        "alpha-lqs.ff.avast.com"],
    "telemetry":      ["analytics.ff.avast.com", "submit.sb.avast.com"],
    "norton-license": ["cebe.norton.com"],
}
IKE_HOSTNAME_CANDIDATES = ["ikev2.hidemyass.com", "ikev2.hma.com"]
NOS_SRV = "_nos._tcp.nos.avast.com"
GEO_URL = "https://ip-info.ff.avast.com/v2/info"

PROBE_PORTS = [80, 443, 7500]

# ---------------------------------------------------------------- probes

def tcp_probe(host, port, timeout=3.0):
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        return {"ok": False, "err": "dns:%s" % e.errno}
    af, st, _proto, _cn, sa = infos[0]
    s = socket.socket(af, st)
    s.settimeout(timeout)
    try:
        s.connect(sa)
        return {"ok": True}
    except OSError as e:
        return {"ok": False, "err": str(e)}
    finally:
        s.close()

def geo_check(timeout=6.0):
    req = urllib.request.Request(GEO_URL, headers={"User-Agent": "hma-suite/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
        return {"ok": True, "geo": data}
    except (urllib.error.URLError, ValueError, OSError) as e:
        return {"ok": False, "err": str(e)}

# ---------------------------------------------------------------- main

def discover(probe=True, timeout=4.0):
    report = {"nos_srv": [], "hosts": {}, "geo": None}

    try:
        report["nos_srv"] = dns_query(NOS_SRV, QTYPE_SRV, timeout)
    except OSError as e:
        report["nos_srv_err"] = str(e)

    for purpose, hosts in STATIC_HOSTS.items():
        for host in hosts:
            entry = {}
            try:
                entry["ipv4"] = dns_query(host, QTYPE_A, timeout)
            except OSError as e:
                entry["ipv4_err"] = str(e)
            if probe and entry.get("ipv4"):
                entry["tcp"] = {str(p): tcp_probe(host, p, 3.0) for p in PROBE_PORTS}
            report["hosts"].setdefault(purpose, {})[host] = entry

    ike = {}
    for host in IKE_HOSTNAME_CANDIDATES:
        try:
            ike[host] = {"ipv4": dns_query(host, QTYPE_A, timeout)}
        except OSError as e:
            ike[host] = {"ipv4_err": str(e)}
    report["ike_candidates"] = ike

    report["geo"] = geo_check()
    return report

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", metavar="PATH", help="write JSON report to PATH")
    ap.add_argument("--no-probe", action="store_true", help="skip TCP probes")
    ap.add_argument("--timeout", type=float, default=4.0, help="DNS timeout")
    args = ap.parse_args()

    report = discover(probe=not args.no_probe, timeout=args.timeout)

    print("== NOS bootstrap (SRV %s)" % NOS_SRV)
    if report["nos_srv"]:
        for prio, weight, port, tgt in report["nos_srv"]:
            print("   gateway: %s:%d (prio %d)" % (tgt, port, prio))
    else:
        print("   no SRV answers (backend bootstrap is normally auth-gated anyway)")

    print("\n== geo check (client's own pre-auth endpoint)")
    g = report["geo"]
    if g["ok"]:
        geo = g["geo"]
        print("   egress: %s (%s), ISP %s" %
              (geo.get("ip"), geo.get("countryName"), geo.get("organization")))
    else:
        print("   failed: %s" % g["err"])

    print("\n== static hosts")
    for purpose, hosts in report["hosts"].items():
        for host, entry in hosts.items():
            ips = ",".join(entry.get("ipv4") or []) or "unresolved"
            line = "   %-16s %-40s %s" % (purpose, host, ips)
            if "tcp" in entry:
                open_ports = [p for p, r in entry["tcp"].items() if r["ok"]]
                if open_ports:
                    line += "  tcp:" + "/".join(open_ports)
            print(line)

    print("\n== IKE hostname candidates (app-internal, may not exist in public DNS)")
    for host, entry in report["ike_candidates"].items():
        ips = ",".join(entry.get("ipv4") or []) or "unresolved"
        print("   %-28s %s" % (host, ips))

    print("\nNote: HMA VPN server lists (per-location tunnel endpoints) are served")
    print("through authenticated APIs only. Feed a server hostname from your HMA")
    print("account into hma_ikev2.py / hma_wg.py — see docs/VM-SETUP.md.")

    if args.json:
        with open(args.json, "w") as fh:
            json.dump(report, fh, indent=2, default=str)
        print("\nJSON report written to %s" % args.json)
    return 0

if __name__ == "__main__":
    sys.exit(main())
