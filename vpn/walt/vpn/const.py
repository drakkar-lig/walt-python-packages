VPN_SOCK_PATH = "/var/run/walt-vpn.sock"
# L2TP tunnel IDs should *not* be:
# * zero (reserved for protocol control messages)
# * if walt-vpn-client and walt-vpn-server are run on the same machine
#   (e.g. when debugging), their IDs should be different
L2TP_SERVER_TUNNEL_ID = 1
L2TP_CLIENT_TUNNEL_ID = 2
L2TP_LOOPBACK_UDP_SPORT = 13998   # feed L2TP interface with packets there
L2TP_LOOPBACK_UDP_DPORT = 13999   # L2TP interface sends packets there
