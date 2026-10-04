#!/usr/bin/env python3
"""Offline unit tests for hma-anywhere — no network, no credentials.

Run:  python3 tests/test_suite.py
CI runs this on every push.
"""
import base64
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "bin"))

failures = []


def check(name, fn):
    try:
        fn()
        print("PASS  %s" % name)
    except Exception as e:
        failures.append((name, e))
        print("FAIL  %s: %s" % (name, e))


# ---------------------------------------------------------------- X25519
def test_x25519_vectors():
    import importlib
    wg = importlib.import_module("hma_wg")
    # RFC 7748 test vector 1
    priv = bytes.fromhex("77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a")
    expect = bytes.fromhex("8520f0098930a754748b7ddcb43ef75a0dbf3a0d26381af4eba4a98eaa9b4e6a")
    assert wg.x25519_public(priv) == expect, "vector 1 mismatch"
    # vector 2: DH shared secret
    priv2 = bytes.fromhex("5dab087e624a8a4b79e17f8b83800ee66f3bb1292618b6fd1c2f8b27ff88e0eb")
    shared = wg._x25519(priv2, expect)
    expect_shared = bytes.fromhex("4a5d9d5ba4ce2de1728e3bf480350f25e07e21c947d19e3376f09b3c1e161742")
    assert shared == expect_shared, "shared secret mismatch"


def test_wg_key_validation():
    import importlib
    wg = importlib.import_module("hma_wg")
    good = base64.b64encode(b"\x01" * 32).decode()
    assert wg.parse_wg_key(good, "t") == b"\x01" * 32
    for bad in ("", "not base64!!", base64.b64encode(b"\x01" * 16).decode()):
        try:
            wg.parse_wg_key(bad, "t")
            raise AssertionError("accepted bad key %r" % bad)
        except SystemExit:
            pass


def test_wg_endpoint_validation():
    import importlib
    wg = importlib.import_module("hma_wg")
    assert wg.parse_endpoint("gw.example.com:51820") == ("gw.example.com", 51820)
    assert wg.parse_endpoint("10.0.0.1:443") == ("10.0.0.1", 443)
    for bad in ("no-port", ":51820", "host:", "host:notaport"):
        try:
            wg.parse_endpoint(bad)
            raise AssertionError("accepted bad endpoint %r" % bad)
        except SystemExit:
            pass


def test_wg_config_generation():
    import importlib, tempfile
    wg = importlib.import_module("hma_wg")
    sys.argv = ["hma_wg.py",
                "--endpoint", "gw.example.com:51820",
                "--peer-pub", base64.b64encode(b"\x09" * 32).decode(),
                "--client-priv", base64.b64encode(b"\x01" * 32).decode(),
                "--address", "10.8.0.2/32", "--firewall", "--mtu", "1420",
                "--out", os.path.join(tempfile.gettempdir(), "test-wg0.conf")]
    try:
        wg.main()
        conf = open(sys.argv[-1]).read()
        assert "[Interface]" in conf and "[Peer]" in conf
        assert "AllowedIPs = 0.0.0.0/0, ::/0" in conf
        assert "MTU = 1420" in conf
        assert "iptables -I OUTPUT" in conf  # kill-switch present
    finally:
        sys.argv = ["hma_wg.py"]


def test_vaar_headers_shape():
    import importlib
    acc = importlib.import_module("hma_account")
    h = acc.default_vaar_headers()
    for k in ("Vaar-Version", "Vaar-Header-Device-Id", "Vaar-Header-Device-Platform",
              "Vaar-Header-App-Build-Version", "Vaar-Header-App-Product-Brand"):
        assert k in h, "missing header %s" % k
    # placeholders must not be real device identifiers
    assert h["Vaar-Header-Device-Id"].startswith("0A0B0C0D"), "embedded real device id?"


def test_ikev2_generation():
    import importlib, tempfile
    ik = importlib.import_module("hma_ikev2")
    out = tempfile.mkdtemp()
    sys.argv = ["hma_ikev2.py", "--server", "gw.example.com",
                "--username", "t@example.com", "--password", "x",
                "--out", out]
    try:
        ik.main()
        swanctl = open(os.path.join(out, "strongswan", "swanctl.conf")).read()
        assert "gw.example.com" in swanctl and "eap-mschapv2" in swanctl
        assert "{{" not in swanctl and "}}" not in swanctl  # format escapes leaked?
        secrets = open(os.path.join(out, "legacy", "ipsec.secrets")).read()
        assert ': EAP "x"' in secrets
        mc = os.path.join(out, "apple", "HMA-iKEv2.mobileconfig")
        assert "IKEv2" in open(mc).read()
        assert (os.stat(os.path.join(out, "legacy", "ipsec.secrets"))
                    .st_mode & 0o777) == 0o600
    finally:
        sys.argv = ["hma_ikev2.py"]


def test_discover_host_table():
    import importlib
    disc = importlib.import_module("hma_discover")
    assert "update-cdn" in disc.STATIC_HOSTS
    assert "mac-vpn.u.avcdn.net" in sum(disc.STATIC_HOSTS.values(), [])
    # DNS encoder sanity
    q = disc._encode_qname("nos.avast.com")
    assert q == b"\x03nos\x05avast\x03com\x00"


check("x25519_rfc7748_vectors", test_x25519_vectors)
check("wg_key_validation", test_wg_key_validation)
check("wg_endpoint_validation", test_wg_endpoint_validation)
check("wg_config_generation", test_wg_config_generation)
check("vaar_headers_shape_no_real_ids", test_vaar_headers_shape)
check("ikev2_generation", test_ikev2_generation)
check("discover_host_table", test_discover_host_table)

print()
if failures:
    print("%d FAILED" % len(failures))
    sys.exit(1)
print("all tests passed")
