#!/bin/bash

set -e

CA_PUB_KEY="%(ca_pub_key)s"
WALT_SERVER="%(walt_server)s"

if [ $(id -u) -ne 0 ]; then
    echo "This script should be run as root. Trying sudo..."
    exec sudo "$0" "$@"
fi

if [ -d '/home/walt-vpn' ]
then
    echo "Sorry, this machine seems to be already configured (directory '/home/walt-vpn' already exists). Giving up." >&2
    exit 1
fi

if [ -d '/var/lib/walt/vpn-endpoint' ]
then
    echo "You are running this script on walt server itself!" >&2
    echo "This script should be run to set up an SSH proxy on another machine. Giving up." >&2
    exit 1
fi

echo "Creating user 'walt-vpn'"
useradd walt-vpn
mkdir -p /home/walt-vpn/.ssh

echo "Creating file /home/walt-vpn/.ssh/authorized_keys"
cat > /home/walt-vpn/.ssh/authorized_keys << EOF
# walt VPN access
cert-authority,restrict,agent-forwarding,command="ssh -q -T -A -o PreferredAuthentications=publickey -o ConnectTimeout=10 walt-vpn@$WALT_SERVER \$SSH_ORIGINAL_COMMAND" $CA_PUB_KEY
EOF
chmod 600 /home/walt-vpn/.ssh/authorized_keys

echo "Creating file /home/walt-vpn/.ssh/known_hosts"
ssh-keyscan -H "$WALT_SERVER" >/home/walt-vpn/.ssh/known_hosts 2>/dev/null
chmod 600 /home/walt-vpn/.ssh/known_hosts

echo "Updating ownership of these new files"
chown -R walt-vpn:walt-vpn /home/walt-vpn

echo "Done."
