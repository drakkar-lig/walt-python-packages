BRIDGE_INTF = "walt-net"
VPN_SOCK_PATH = "/var/run/walt-vpn.sock"
# L2TP tunnel IDs should *not* be:
# * zero (reserved for protocol control messages)
# * if walt-vpn-client and walt-vpn-server are run on the same machine
#   (e.g. when debugging), their IDs should be different
L2TP_SERVER_TUNNEL_ID = 1
L2TP_CLIENT_TUNNEL_ID = 2
L2TP_LOOPBACK_UDP_SPORT = 13998   # feed L2TP interface with packets there
L2TP_LOOPBACK_UDP_DPORT = 13999   # L2TP interface sends packets there
# the MTU on L2TP interface allows to define the maximum L2TP packet size
# walt-vpn-client and walt-vpn-server may receive (as UDP payload), thus
# define their packet buffer sizes.
# for alignment to memory pages we want a buffer size of 4096 bytes per packet.
# packets are made of:
# - L2TP header (max 16 bytes)
# - ethernet header (14 bytes)
# - IP packet (max size defined by MTU)
L2TP_PACKET_MAX_SIZE = 4096
L2TP_HEADER_MAX_SIZE = 16
ETHERNET_HEADER_SIZE = 14
L2TP_INTERFACE_MTU = L2TP_PACKET_MAX_SIZE - (L2TP_HEADER_MAX_SIZE + ETHERNET_HEADER_SIZE)
