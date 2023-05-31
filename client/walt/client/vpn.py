import os
import sys

from walt.client.application import WalTApplication, WalTCategoryApplication
from walt.client.link import ClientToServerLink, connect_to_tcp_server
from walt.client.tools import yes_or_no
from walt.common.tcp import Requests, write_pickle


class WalTVPN(WalTCategoryApplication):
    """VPN related sub-commands"""

    ORDERING = 5


WAIT_VPN_BUSY_LABEL = "Waiting for next VPN connection attempt (press ctrl-C to stop)"


@WalTVPN.subcommand("monitor")
class WalTVPNMonitor(WalTApplication):
    """monitor VPN and accept/deny new connection requests"""

    def main(self):
        with ClientToServerLink() as server:
            while True:
                server.set_busy_label(WAIT_VPN_BUSY_LABEL)
                try:
                    device_mac = server.vpn_wait_grant_request()
                except KeyboardInterrupt:
                    print()
                    break
                print("New VPN access request from device " + device_mac + ".")
                grant_ok = yes_or_no("Should this device be granted VPN access?")
                print("Transmitting to walt server...")
                server.set_default_busy_label()
                result, comment = server.vpn_respond_grant_request(device_mac, grant_ok)
                if result == "OK":
                    print(comment)
                else:
                    print("FAILED! " + comment)


@WalTVPN.subcommand("setup-proxy")
class WalTVPNSetupProxy(WalTApplication):
    """setup an ssh frontend server as a WalT VPN proxy"""

    def main(self):
        with ClientToServerLink() as server:
            script_content = server.get_vpn_proxy_setup_script()
            with open("proxy-setup.sh", "w") as f:
                f.write(script_content)
                os.fchmod(f.fileno(), 0o755)  # set it executable
        print("A script 'proxy-setup.sh' has been generated in current directory.")
        print("Copy and run it on the host you want to use as a walt vpn proxy.")


def read_vpn_node_image(entrypoint):
    # connect to server
    sock = connect_to_tcp_server()
    # send the request id
    Requests.send_id(sock, Requests.REQ_VPN_NODE_IMAGE)
    # wait for the READY message from the server
    sock.readline()
    # write the parameters
    write_pickle(dict(model="rpi-3-b-plus", entrypoint=entrypoint), sock)
    # initial communication loop
    while True:
        line = sock.readline().decode("UTF-8").strip()
        words = line.split()
        if words[0] == "MSG":
            print(" ".join(words[1:]))
        elif words[0] == "ERR":
            print(" ".join(words[1:]), file=sys.stderr)
            return
        elif words[0] == "START":
            break
        else:
            print("Unexpected communication issue with walt server!", file=sys.stderr)
            return
    # starting transfer
    with open("rpi3bp-vpn.dd", "wb") as f:
        while True:
            chunk = sock.read(2048)
            if len(chunk) == 0:
                break
            f.write(chunk)
    sock.close()
    print("A file 'rpi3bp-vpn.dd' has been generated in current directory.")
    print(
        "Flash it (using dd tool or similar) on the SD card of the rpi3b+ board you"
        " want to use as a VPN node."
    )


@WalTVPN.subcommand("setup-node")
class WalTVPNSetupNode(WalTApplication):
    """setup a WalT VPN node"""

    def main(self):
        print(
            "Note: for now only raspberry pi 3B+ boards can be used as a walt VPN node."
        )
        print("This procedure will generate an appropriate SD card image.")
        entrypoint = ""
        while entrypoint == "":
            print(
                (
                    "Please indicate the WalT VPN entrypoint (hostname or IP address)"
                    " this node will connect to:"
                ),
                end=" ",
            )
            entrypoint = input()
        print("OK.\n")
        read_vpn_node_image(entrypoint)
