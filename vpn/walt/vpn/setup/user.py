from pathlib import Path

from walt.common.constants import UNSECURE_ECDSA_KEYPAIR
from walt.common.tools import chown_tree, do

WALT_VPN_USER = dict(
    home_dir=Path("/var/lib/walt/vpn"),
    authorized_keys_pattern="""
# walt VPN secured access
cert-authority,restrict,command="walt-vpn-endpoint" %(ca_pub_key)s
# walt VPN authentication step
restrict,command="walt-vpn-auth-tool $SSH_ORIGINAL_COMMAND" %(unsecure_pub_key)s
""",
)

VPN_CA_KEY = WALT_VPN_USER["home_dir"] / ".ssh" / "vpn-ca-key"
VPN_CA_KEY_PUB = WALT_VPN_USER["home_dir"] / ".ssh" / "vpn-ca-key.pub"

UNSECURE_KEY_PUB = UNSECURE_ECDSA_KEYPAIR["openssh-pub"].decode("ascii")


def setup_user():
    home_dir = WALT_VPN_USER["home_dir"]
    if not home_dir.exists():  # if not configured
        # create user walt-vpn
        do("useradd -U -d %(home_dir)s walt-vpn" % dict(home_dir=str(home_dir)))
        # generate VPN CA key
        VPN_CA_KEY.parent.mkdir(parents=True)
        do("ssh-keygen -N '' -t ecdsa -b 521 -f %s" % str(VPN_CA_KEY))
        ca_pub_key = VPN_CA_KEY_PUB.read_text().strip()
        # create appropriate authorized_keys file
        authorized_keys_file = home_dir / ".ssh" / "authorized_keys"
        authorized_keys_file.write_text(
            WALT_VPN_USER["authorized_keys_pattern"]
            % dict(ca_pub_key=ca_pub_key, unsecure_pub_key=UNSECURE_KEY_PUB)
        )
        # fix owner to 'walt-vpn'
        chown_tree(home_dir, "walt-vpn", "walt-vpn")
