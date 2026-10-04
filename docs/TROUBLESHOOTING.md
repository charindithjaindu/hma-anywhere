# Troubleshooting

Symptom-indexed fixes for the whole suite. If your symptom isn't here, run
the two diagnostics first and include their output in any bug report:

```bash
./check-egress.sh                          # what does the tunnel actually do?
systemctl status openvpn-client@hma danted tinyproxy hma-watchdog.timer
journalctl -u openvpn-client@hma -n 50 --no-pager
```

## Tunnel

### SSH died after the tunnel came up

`setup-netrules.sh` wasn't run (or ran after the tunnel). From your VPS
provider's console:

```bash
sudo ip rule del from <VPS_PUBLIC_IP> lookup 200 2>/dev/null
sudo /usr/local/sbin/hma-netrules     # or: sudo hma-anywhere/vps/setup-netrules.sh
```

Prevention: run `setup-netrules.sh` **before** the first tunnel start; it's
installed as a boot-time service after that.

### `select-country.sh` exits 2 ("tunnel failed to come up")

```bash
journalctl -u openvpn-client@hma -n 30
```

- `AUTH_FAILED` / auth errors → check `/etc/openvpn/hma/hma.creds` (email +
  password of your HMA account, two lines, file mode 600).
- `TLS Error` / timeouts → that endpoint may be blocked from your provider;
  try another country's config, or a port-443 variant from HMA's configs.
- `Cannot open device tun` → openvpn needs CAP_NET_ADMIN; you did run with
  sudo, right?

### Tunnel is up but no traffic

- Provider blocks the config's port — try another config variant.
- DNS: test `curl --interface tun0 -sS https://1.1.1.1` — if IP works but
  names don't, ensure apps use the proxy (`socks5h`) rather than local DNS.

### Tunnel keeps dying

The watchdog restarts it every 2 min — if it *stays* down, read the journal
above. Persistent auth failure usually means device-slot overuse (see
Licensing below) or expired subscription (check with
`hma_account.py licenses`).

## Proxies

### `connection refused` through the proxy

That's the **fail-closed guarantee** doing its job — the tunnel is down.
Check `systemctl status openvpn-client@hma`, fix the tunnel, the proxy
recovers on its own (no restart needed).

### Proxy works but egress shows the VPS IP

`/etc/danted.conf` has the wrong `external:` (pointing at the public
interface instead of the tunnel). Re-run `setup-proxy.sh` with the tunnel
up, or set `TUNIF=<iface>` explicitly. Then `systemctl restart danted`.

### Apps in Docker can't reach 127.0.0.1

Containers have their own loopback. Either point them at the VM's `docker0`
IP (usually `172.17.0.1`) and allow it in dante:

```
# /etc/danted.conf — add next to the 127.0.0.1 block
internal: 172.17.0.1 port = 1080
client pass { from: 172.16.0.0/12 to: 0.0.0.0/0  log: error }
socks pass  { from: 172.16.0.0/12 to: 0.0.0.0/0  protocol: tcp udp
              method: username  log: error }
```

then `systemctl restart danted` — or run the app with `--network host`.

### DNS leaks (geo sites see the VPS's resolver)

Use `socks5h://` (not `socks5://`) in SOCKS clients, or the HTTP proxy —
both route the hostname through the tunnel. tinyproxy does this by default.

## Country / rotation

### `select-country.sh` says "no config for XX"

You haven't installed that country's config. Download it from the HMA
dashboard and place it as `/etc/openvpn/hma/XX.conf`.

### `rotate.sh` says the egress IP is unchanged

The config for that country may pin a single `remote` server whose load
balancer keeps your session IP. Options: add more of that country's server
configs, switch country entirely, or try again later (gateway pools change).

### Wrong country shows up in geo checks

OpenVPN connects to the first reachable `remote` line — a config file
downloaded for "UK - London" may contain other UK cities; that's normal.
Check which server you're on: `grep ^remote $(readlink /etc/openvpn/client/hma.conf)`.

## Licensing / account

### `400 Cannot parse Vaar request`

Missing/incorrect Vaar headers — use `hma_account.py` as-is (it builds the
envelope), don't hand-roll the request without the full header set
(documented in [ACCOUNTS.md](ACCOUNTS.md)).

### `activate` fails on the VM ("alphacli not found")

Expected — redemption is protobuf-only and needs the vendor CLI. Redeem once
via [my.hma.com](https://my.hma.com) or on a machine with the HMA app, then
continue. See [Getting started, Step 1](GETTING-STARTED.md#step-1-activate-your-subscription).

### License query shows `overused: true` / connection rejected

Too many active devices on the subscription (HMA: typically 5). Remove an
old device in your HMA account, or `sudo ./select-country.sh current` after
a slot frees up. The suite never deletes devices for you.

### `licenses` returns HTTP 4xx with a wallet key

- 400 → malformed wallet key (format `XXXXXX-XXXXXX-XXXXXX`).
- 403/404 → key not valid for this endpoint; verify via `status` on the
  machine with the HMA app, or `login` (email flow).

## Watchdog / systemd

### Watchdog restarts the tunnel in a loop

`hma-watchdog` only acts when the unit is inactive — a restart loop means
the tunnel can't stay up. Stop the timer while debugging:
`sudo systemctl disable --now hma-watchdog.timer` (re-enable with
`--now` when fixed).

### Rules don't survive reboot

`hma-netrules.service` is enabled at bootstrap; check
`systemctl is-enabled hma-netrules`. If you rebuilt networking (netplan
changes etc.), re-run `setup-netrules.sh`.

---

Still stuck? Open an issue with the output of the three diagnostic commands
at the top.
