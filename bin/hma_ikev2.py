#!/usr/bin/env python3
"""hma_ikev2.py — generate ready-to-use IKEv2/IPsec profiles for HMA VPN.

IKEv2 is the only *standard* protocol HMA's client speaks that works with just
your HMA account credentials (username + password via EAP) — no per-session
keys required. Server hostnames come from your HMA account/dashboard or the
manual-configuration docs; verify a candidate first with hma_probe.py --ike.

Generates:
  strongswan/swanctl.conf      modern strongSwan (5.x, swanctl/vici)
  strongswan/strongsnippets    extra strongswan.conf bits
  legacy/ipsec.conf            legacy ipsec/starter config
  legacy/ipsec.secrets         EAP credentials (chmod 600!)
  apple/HMA-iKEv2.mobileconfig native macOS/iOS profile (EAP)
  windows/ connect.ps1         Windows built-in IKEv2 (EAP-MSCHAPv2)

Usage:
  python3 hma_ikev2.py --server IKEV2-HOST --username you@example.com \
      [--password ...] [--remote-id REMOTE_ID] [--out OUTDIR] [--name hma]
Password is read interactively if not supplied (and never echoed).
"""
import argparse
import getpass
import os
import sys

MOBILECONFIG = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>PayloadContent</key>
  <array>
    <dict>
      <key>IKEv2</key>
      <dict>
        <key>AuthenticationMethod</key>
        <string>None</string>
        <key>ChildSecurityAssociationParameters</key>
        <dict>
          <key>EncryptionAlgorithm</key><integer>3</integer>
          <key>IntegrityAlgorithm</key><integer>2</integer>
          <key>DHGroup</key><integer>14</integer>
          <key>LifeTimeInMinutes</key><integer>1440</integer>
        </dict>
        <key>DeadPeerDetectionRate</key>
        <string>Medium</string>
        <key>DisableRedirect</key>
        <true/>
        <key>EnableFallback</key>
        <true/>
        <key>ExtendedAuthEnabled</key>
        <integer>1</integer>
        <key>AuthName</key>
        <string>{username}</string>
        <key>AuthPassword</key>
        <string>{password}</string>
        <key>IKESecurityAssociationParameters</key>
        <dict>
          <key>EncryptionAlgorithm</key><integer>3</integer>
          <key>IntegrityAlgorithm</key><integer>2</integer>
          <key>DHGroup</key><integer>14</integer>
          <key>LifeTimeInMinutes</key><integer>1440</integer>
        </dict>
        <key>LocalIdentifier</key>
        <string>{username}</string>
        <key>NATKeepAliveInterval</key>
        <integer>20</integer>
        <key>NATKeepAliveOffloadEnable</key>
        <true/>
        <key>RemoteAddress</key>
        <string>{server}</string>
        <key>RemoteIdentifier</key>
        <string>{remote_id}</string>
        <key>ServerAddresses</key>
        <array>
          <string>1.1.1.1</string>
          <string>1.0.0.1</string>
        </array>
      </dict>
      <key>IPv4</key>
      <dict>
        <key>OverridePrimary</key>
        <integer>1</integer>
      </dict>
      <key>PayloadDescription</key>
      <string>HMA VPN via IKEv2 (EAP)</string>
      <key>PayloadDisplayName</key>
      <string>{name} VPN (IKEv2)</string>
      <key>PayloadIdentifier</key>
      <string>local.hma-anywhere.ikev2.{name}</string>
      <key>PayloadOrganization</key>
      <string>hma-anywhere</string>
      <key>PayloadType</key>
      <string>com.apple.vpn.managed</string>
      <key>PayloadUUID</key>
      <string>{uuid}</string>
      <key>PayloadVersion</key>
      <integer>1</integer>
      <key>VPNType</key>
      <string>IKEv2</string>
    </dict>
  </array>
  <key>PayloadDisplayName</key>
  <string>{name} VPN (IKEv2)</string>
  <key>PayloadIdentifier</key>
  <string>local.hma-anywhere.ikev2.{name}.top</string>
  <key>PayloadRemovalDisallowed</key>
  <false/>
  <key>PayloadType</key>
  <string>Configuration</string>
  <key>PayloadUUID</key>
  <string>{uuid2}</string>
  <key>PayloadVersion</key>
  <integer>1</integer>
</dict>
</plist>
"""

SWANCTL = """# strongSwan swanctl configuration — load with:  sudo swanctl --load-all
connections {
    @NAME@ {
        version = 2
        local_addrs = %any
        remote_addrs = @SERVER@

        local {
            auth = eap-@EAP@
            eap_id = @USERNAME@
        }
        remote {
            auth = pubkey
            id = @REMOTE_ID@
        }
        children {
            @NAME@-child {
                local_ts = 0.0.0.0/0, ::/0
                remote_ts = 0.0.0.0/0, ::/0
                esp_proposals = aes256gcm16-prfsha256-modp2048
                dpd_action = restart
                start_action = none   # set to 'start' for connect-on-boot
            }
        }
        proposals = aes256-sha256-modp2048
        dpd_delay = 30s
        dpd_timeout = 120s
        mobike = yes
        rekey_time = 0s
        reauth_time = 0s
        fragmentation = yes
    }
}

secrets {
    eap-@NAME@ {
        id = @USERNAME@
        secret = "@PASSWORD@"
    }
}
"""

IPSEC_LEGACY = """# legacy ipsec.conf (ipsec/starter) — /etc/ipsec.conf
conn {name}
    keyexchange=ikev2
    type=tunnel
    left=%defaultroute
    leftsourceip=%config
    leftauth=eap-{eap}
    eap_identity={username}
    right={server}
    rightid={remote_id}
    rightauth=pubkey
    ike=aes256-sha256-modp2048!
    esp=aes256gcm16-modp2048!
    dpddelay=30
    dpdtimeout=120
    dpdaction=restart
    auto=add
"""

IPSEC_SECRETS = """# /etc/ipsec.secrets — keep 0600, root-owned
{username} : EAP "{password}"
"""

WINDOWS_PS = """# Run as Administrator in PowerShell (Windows 10/11 built-in IKEv2)
Add-VpnConnection `
  -Name "{name} VPN" `
  -ServerAddress "{server}" `
  -TunnelType IKEv2 `
  -AuthenticationMethod EAP `
  -EncryptionLevel Required `
  -RememberCredential `
  -SplitTunneling:$false

# Optional: force the stronger ciphers (match macOS/strongSwan profile)
# Set-VpnConnectionIPsecConfiguration -ConnectionName "{name} VPN" `
#   -AuthenticationTransformConstants SHA256 -CipherTransformConstants AES256 `
#   -EncryptionMethod AES256 -IntegrityMethod SHA256 -DHGroup Group14 `
#   -PfsGroup None -Force
# Credentials are entered on first connect (EAP prompt).
"""

def make_uuid():
    import uuid
    return str(uuid.uuid4())

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server", required=True, help="IKEv2 gateway hostname/IP")
    ap.add_argument("--username", required=True, help="HMA account username/email")
    ap.add_argument("--password", help="HMA password (prompted if omitted)")
    ap.add_argument("--remote-id", help="gateway IKE identity (default: server)")
    ap.add_argument("--eap", default="mschapv2", choices=["mschapv2", "md5", "gtc"],
                    help="EAP method (default mschapv2)")
    ap.add_argument("--name", default="hma", help="profile/connection name")
    ap.add_argument("--out", default="hma-ikev2-out", help="output directory")
    args = ap.parse_args()

    password = args.password or getpass.getpass("HMA password for %s: " % args.username)
    remote_id = args.remote_id or args.server

    out = args.out
    for sub in ("strongswan", "legacy", "apple", "windows"):
        os.makedirs(os.path.join(out, sub), exist_ok=True)

    def w(rel, content, mode=0o644):
        path = os.path.join(out, rel)
        with open(path, "w") as fh:
            fh.write(content)
        os.chmod(path, mode)
        print("wrote %s" % path)

    subs = dict(name=args.name, server=args.server, username=args.username,
                password=password, remote_id=remote_id, eap=args.eap,
                uuid=make_uuid(), uuid2=make_uuid())

    swanctl = (SWANCTL
               .replace("@NAME@", subs["name"])
               .replace("@SERVER@", subs["server"])
               .replace("@USERNAME@", subs["username"])
               .replace("@REMOTE_ID@", subs["remote_id"])
               .replace("@EAP@", subs["eap"])
               .replace("@PASSWORD@", subs["password"]))

    w("strongswan/swanctl.conf", swanctl)
    w("legacy/ipsec.conf", IPSEC_LEGACY.format(**subs))
    w("legacy/ipsec.secrets", IPSEC_SECRETS.format(**subs), mode=0o600)
    w("apple/HMA-iKEv2.mobileconfig", MOBILECONFIG.format(**subs))
    w("windows/connect.ps1", WINDOWS_PS.format(**subs))

    print("""
Next steps (see docs/VM-SETUP.md for detail):
  Linux/strongSwan : cp strongswan/swanctl.conf /etc/swanctl/conf.d/
                     sudo swanctl --load-all && sudo swanctl --initiate --child {name}-child
  Linux/legacy     : cp legacy/ipsec.conf /etc/ ; cp legacy/ipsec.secrets /etc/
                     sudo ipsec restart && sudo ipsec up {name}
  macOS/iOS VM     : double-click apple/HMA-iKEv2.mobileconfig (System Settings > VPN)
  Windows VM       : run windows/connect.ps1 as Administrator
NOTE: {server} must be a valid IKEv2 gateway for your account — verify it
first with:  python3 hma_probe.py --ike {server}
""".format(**subs))
    return 0

if __name__ == "__main__":
    sys.exit(main())
