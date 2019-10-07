import os
from plumbum import cli
from walt.client.link import ClientToServerLink
from walt.client.application import WalTCategoryApplication, WalTApplication
from walt.client.tools import yes_or_no

class WalTVPN(WalTCategoryApplication):
    """VPN related sub-commands"""
    pass

WAIT_VPN_BUSY_LABEL='\
Waiting for next VPN connection attempt (press ctrl-C to stop)'

@WalTVPN.subcommand("monitor")
class WalTVPNMonitor(WalTApplication):
    """Monitor VPN and accept/deny new connection requests"""
    def main(self):
        with ClientToServerLink() as server:
            while True:
                server.set_busy_label(WAIT_VPN_BUSY_LABEL)
                try:
                    device_mac = server.vpn_wait_grant_request()
                except KeyboardInterrupt:
                    print()
                    break
                print('New VPN access request from device ' + device_mac + '.')
                grant_ok = yes_or_no('Should this device be granted VPN access?')
                print('Transmitting to walt server...')
                server.set_default_busy_label()
                result, comment = server.vpn_respond_grant_request(device_mac, grant_ok)
                if result == 'OK':
                    print(comment)
                else:
                    print('FAILED! ' + comment)

@WalTVPN.subcommand("setup-proxy")
class WalTVPNSetupProxy(WalTApplication):
    """Setup an ssh frontend server as a WalT VPN proxy"""
    def main(self):
        with ClientToServerLink() as server:
            script_content = server.get_vpn_proxy_setup_script()
            with open('proxy-setup.sh', 'w') as f:
                f.write(script_content)
                os.fchmod(f.fileno(), 0o755)    # set it executable
        print("A script 'proxy-setup.sh' has been generated in current directory.")
        print("Copy and run it on the host you want to use as a walt vpn proxy.")
