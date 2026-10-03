#!/usr/bin/env python3
"""hma_probe.py — reachability probes for candidate VPN endpoints.

Two modes:

  TCP probe   — does host:port accept a TCP connection?
  IKE probe   — sends a minimal IKE_SA_INIT (UDP 500) and reports whether an
                IKEv2 responder answers. Useful to validate an HMA IKEv2 server
                hostname before wiring it into strongSwan / a native client.
                A timeout is INCONCLUSIVE (your network may block outbound UDP
                500); a reply proves a responder.

Usage:
  python3 hma_probe.py --tcp SERVER --ports 443,51820
  python3 hma_probe.py --ike SERVER [--ports 500,4500]
"""
import argparse
import os
import socket
import struct
import sys

# ---------------------------------------------------------------- IKE probe
# Minimal IKE_SA_INIT initiator (RFC 7296). We deliberately send a simple but
# well-formed proposal; any reply (including INVALID_KE_PAYLOAD / NO_PROPOSAL
# notifications) proves an IKE responder is present.

EXCH_IKE_SA_INIT = 34

def _ike_payload(next_type, data):
    # generic payload header: next, critical/reserved, length(total)
    return struct.pack(">BBH", next_type, 0, 4 + len(data)) + data

def _sa_payload_body():
    # Proposal #1: IKE, ENCR AES-CBC(12) 128/256, PRF SHA2-256(5),
    #              INTEG SHA2-256-128(12), DH group 14 (2048-bit MODP)
    def transform(ttype, tid, attrs=b""):
        return struct.pack(">BBH", 3, 0, 8 + len(attrs)) + \
               struct.pack(">BBH", ttype, 0, tid) + attrs
    t = (transform(1, 12, struct.pack(">HHH", 14, 128, 0)) +   # ENCR keylen attr
         transform(1, 12, struct.pack(">HHH", 14, 256, 0)) +
         transform(2, 5) +                                      # PRF
         transform(4, 12) +                                     # INTEG
         transform(4, 14))                                      # DH
    # proposal header: last-substruct, rsv, len, prop-num, proto-id(1=IKE), spi-size(0), num-transforms
    n = 5
    prop = struct.pack(">BBBBBBB", 0, 0, 8 + len(t), 1, 1, 0, n) + t
    return prop

def _ke_payload():
    # DH group 14; send a syntactically valid-length (256-byte) public value.
    # Real responders that care will answer with INVALID_KE_PAYLOAD — still proof.
    return struct.pack(">HH", 14, 0) + b"\x02" + os.urandom(255)

def craft_ike_sa_init():
    isi = os.urandom(8)                       # initiator SPI
    # RFC 7296 header: iSPI(8) rSPI(8) next(1) ver(1) exch(1) flags(1) msgid(4) len(4)
    hdr = struct.pack(">QQBBBBII", int.from_bytes(isi, "big"), 0, 33, 0x20,
                      EXCH_IKE_SA_INIT, 0x08, 0, 0)
    # payload chain: SA(33) -> KE(34) -> Nonce(40) -> end(0), built backwards
    nonce = _ike_payload(0, os.urandom(32))
    ke = _ike_payload(40, _ke_payload())
    sa = _ike_payload(34, _sa_payload_body())
    msg = hdr + sa + ke + nonce
    msg = msg[:24] + struct.pack(">I", len(msg)) + msg[28:]
    return isi, msg

def ike_probe(host, port, timeout=4.0):
    isi, msg = craft_ike_sa_init()
    af = socket.AF_INET6 if ":" in host else socket.AF_INET
    try:
        sa = socket.getaddrinfo(host, port, af, socket.SOCK_DGRAM)[0][4]
    except socket.gaierror as e:
        return {"ok": False, "inconclusive": True, "err": "dns: %s" % e}
    s = socket.socket(af, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        s.sendto(msg, sa)
        data, _ = s.recvfrom(4096)
        note = ""
        if len(data) >= 28 and data[18] == 34:  # reply to IKE_SA_INIT
            if len(data) >= 36:
                # notification payload often follows; try to read notify type
                note = " (IKE_SA_INIT response)"
        return {"ok": True, "bytes": len(data), "note": note}
    except socket.timeout:
        return {"ok": False, "inconclusive": True,
                "err": "no reply within %ss (outbound UDP may be filtered)" % timeout}
    except OSError as e:
        return {"ok": False, "inconclusive": True, "err": str(e)}
    finally:
        s.close()

# ---------------------------------------------------------------- TCP probe

def tcp_probe(host, port, timeout=3.0):
    af = socket.AF_INET6 if ":" in host else socket.AF_INET
    try:
        sa = socket.getaddrinfo(host, port, af, socket.SOCK_STREAM)[0][4]
    except socket.gaierror as e:
        return {"ok": False, "err": "dns: %s" % e}
    s = socket.socket(af, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(sa)
        return {"ok": True}
    except OSError as e:
        return {"ok": False, "err": str(e)}
    finally:
        s.close()

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tcp", metavar="HOST", help="TCP-probe HOST")
    ap.add_argument("--ike", metavar="HOST", help="IKE-probe HOST (UDP 500/4500)")
    ap.add_argument("--ports", default="", help="comma-separated ports")
    ap.add_argument("--timeout", type=float, default=4.0)
    args = ap.parse_args()

    if not args.tcp and not args.ike:
        ap.error("nothing to do: pass --tcp HOST and/or --ike HOST")

    rc = 0
    if args.tcp:
        ports = [int(p) for p in args.ports.split(",") if p.strip()] or [443]
        for p in ports:
            r = tcp_probe(args.tcp, p, args.timeout)
            status = "OPEN" if r["ok"] else "closed/filtered (%s)" % r.get("err")
            print("tcp %s:%-6d %s" % (args.tcp, p, status))
            rc |= 0 if r["ok"] else 1

    if args.ike:
        ports = [int(p) for p in args.ports.split(",") if p.strip()] or [500, 4500]
        for p in ports:
            r = ike_probe(args.ike, p, args.timeout)
            if r["ok"]:
                print("ike %s:%-6d RESPONDER%s (%d bytes)" %
                      (args.ike, p, r.get("note", ""), r["bytes"]))
            elif r.get("inconclusive"):
                print("ike %s:%-6d inconclusive: %s" % (args.ike, p, r["err"]))
            else:
                print("ike %s:%-6d error: %s" % (args.ike, p, r["err"]))
                rc |= 1
    return rc

if __name__ == "__main__":
    sys.exit(main())
