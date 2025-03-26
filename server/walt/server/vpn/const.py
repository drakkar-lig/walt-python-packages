from pathlib import Path

VPN_SOCK_PATH = "/run/walt-vpn.sock"
VPN_SERVER_PATH = Path("/var/lib/walt/vpn-server")
VPN_ENDPOINT_PATH = Path("/var/lib/walt/vpn-endpoint")
VPN_CA_KEY = VPN_SERVER_PATH / "vpn-ca-key"
VPN_CA_KEY_PUB = VPN_SERVER_PATH / "vpn-ca-key.pub"
VPN_SERVER_KRL = VPN_SERVER_PATH / "revoked.krl"
VPN_HTTP_EP_HISTORY_FILE = VPN_SERVER_PATH / "http-ep-history.pickle"
