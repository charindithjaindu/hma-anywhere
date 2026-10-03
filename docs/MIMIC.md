# Mimic protocol — reimplementation roadmap

Why this file: Mimic is the only HMA tunnel that can't be reused with an
off-the-shelf client. If you ever want a Linux/VM client for it, this is the
map of what has to be rebuilt, in the order I'd attack it, based on what the
macOS binary (`com.privax.osx.provpn.mimictun`, Go, `git.int.avast.com/mimic/`)
leaks in strings and symbols.

## Known architecture (from the binary)

```
App (EngineSE) ──unix socket──▶ mimictun CLI ──TLS1.3(+ECH, +PQE)──▶ gateway
                                   │
                                   ├─ mimic-core  (framing, streams, creds)
                                   ├─ gVisor netstack (pkg/tcpip)  ← TCP/IP in userspace
                                   └─ zx2c4 wireguard  ← data plane INSIDE mimic
```

- Transport: TLS 1.3. Two modes observed:
  - legacy: pinned self-signed CA (`-ca`), mutual auth via user/pass credentials
  - ECH: `-ech-public-key` + `-tlsdomain` (outer SNI ≠ inner SNI), forces TLS 1.3
- Post-quantum: `ApplyPostQuantumMixinAsInitiator` — a *custom* TLS extension
  ("PQE", `mimic/pqe-join`) mixing MLKEM1024-P384 shared secret into the TLS
  key schedule after the handshake (`ServerPinned`/`ClientPinned`).
- Framing: handshake states `Greeted → Open` (Protocol v%N transition string),
  PING/PONG keepalive, `Credentials` message, reconnect (`Reconnect` event),
  `DataOnlyJoin` for extra tunnels (multi-dialer round robin).
- Streams: "weaver"/"looper" threads, per-stream flow control
  (`mimicconfig.SetFlowControlDisabled`, WindowUpdate throttling).
- Data plane: once open, it tunnels WireGuard transport packets; netstack
  bridges TCP/UDP/DNS (DNS-over-TCP bridge, DNS proxy txID pool).

## Attack order

1. **TLS visibility** — run the macOS `mimictun` (macOS VM, root, `-log ...`)
   against a gateway while capturing with a MITM proxy that accepts its CA
   (legacy `-ca` mode makes this trivial: pin the CA yourself). This gives you
   the protobuf plaintext of the handshake without touching the PQE layer
   (PQE is only enforced when the server requires it — the flags suggest it's
   negotiable: `negotation for proto [%s] resulted in [%s]`).
2. **Framing recovery** — dump Greeted→Open exchange; `Credentials` message
   shape; stream-open/stream-data/window-update opcodes. Go protobuf
   descriptors are embedded in the binary — extract with a protobuf
   descriptor walker (the types `messages.Credentials`, `wrapper.*` are in the
   type table).
3. ** reimplement a minimal client in Go** — honestly the fastest route is
   *linking the extracted mimic-core packages* is impossible (internal repo),
   but a ~1-2kline Go client speaking framing-over-TLS is realistic once (2)
   is done. WireGuard data plane you get for free (wireguard-go).
4. **PQE** — only needed if the gateway enforces it; reverse
   `ApplyPostQuantumMixinAsInitiator` in the binary (Go符号/objdump), likely an
   HKDF mix-in of the ML-KEM shared secret into the TLS exporter. MLKEM1024
   implementations exist (liboqs, mlkem go modules).

## Reality check

Effort estimate: the framing client is a weekend-grade project; PQE+ECH parity
is a multi-week project. For general VM use, IKEv2 (path A) or WireGuard
(path B) get you the same network effect with none of this work — Mimic only
matters if you specifically need DPI-resistance *and* want to understand it.
