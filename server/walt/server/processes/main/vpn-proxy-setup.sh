#!/bin/bash

set -e

if [ $(id -u) -ne 0 ]; then
    echo "This script should be run as root. Trying sudo..."
    exec sudo "$0" "$@"
fi

if [ -d '/home/walt-vpn' ]
then
    echo "Sorry, this machine seems to be already configured (directory '/home/walt-vpn' already exists). Giving up." >&2
    exit 1
fi

if [ -d '/var/lib/walt/vpn' ]
then
    echo "You are running this script on walt server itself!" >&2
    echo "This script should be run to set up a VPN proxy on another machine. Giving up." >&2
    exit 1
fi

walt_host=""
while [ "$walt_host" = "" ]
do
    read -p "Enter the hostname or IP of walt server (or next proxy in case of several hops): " walt_host
done

echo "Creating user 'walt-vpn'"
useradd walt-vpn

echo "Creating file /home/walt-vpn/.ssh/authorized_keys"
mkdir -p /home/walt-vpn/.ssh
cat > /home/walt-vpn/.ssh/authorized_keys << EOF
# walt VPN secured access
cert-authority,restrict,agent-forwarding,command="ssh -q -T -A -o PreferredAuthentications=publickey -o ConnectTimeout=10 walt-vpn@$walt_host" %(ca_pub_key)s
# walt VPN authentication step
restrict,agent-forwarding,command="ssh -T -q -A -o PreferredAuthentications=publickey -o StrictHostKeyChecking=no -o ConnectTimeout=10 walt-vpn@$walt_host \$SSH_ORIGINAL_COMMAND" %(unsecure_pub_key)s
EOF
chown -R walt-vpn:walt-vpn /home/walt-vpn

echo "Done."


