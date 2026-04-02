#!/usr/bin/env python3
"""
Custom DHCP server for the WALT platform.

Handles PXE booting for x86 and Raspberry Pi boards (including the RPi3B+
firmware bug where boot continues after DHCPOFFER without waiting for DHCPACK).

Packet format reference: RFC 2131
Options reference: RFC 2132, RFC 3397 (domain search list)
"""

import pickle
import socket
import struct
from dataclasses import dataclass, field
from time import time
from typing import Optional

from walt.common.apilink import ServerAPILink
from walt.common.evloop import EventLoop
from walt.common.unix import UnixServer
from walt.server.const import DHCPD_HEARTBEAT_PERIOD
from walt.server.const import DHCPD_DEVICES_FILE, DHCPD_CTRL_SOCK_PATH
from walt.server.tools import get_walt_subnet, get_server_ip
from walt.server.tools import get_rpi_foundation_mac_vendor_ids
from walt.server.tools import get_netgear_mac_vendor_ids, notify_systemd

DEBUG_LEASES = True
WALT_SUBNET = get_walt_subnet()
WALT_SERVER_IP = get_server_ip()

# ---------------------------------------------------------------------------
# DHCP message types (option 53)
# ---------------------------------------------------------------------------
DHCPDISCOVER = 1
DHCPOFFER    = 2
DHCPREQUEST  = 3
DHCPDECLINE  = 4
DHCPACK      = 5
DHCPNAK      = 6
DHCPRELEASE  = 7
DHCPINFORM   = 8

MSG_TYPE_NAMES = {
    DHCPDISCOVER: "DISCOVER",
    DHCPOFFER:    "OFFER",
    DHCPREQUEST:  "REQUEST",
    DHCPDECLINE:  "DECLINE",
    DHCPACK:      "ACK",
    DHCPNAK:      "NAK",
    DHCPRELEASE:  "RELEASE",
    DHCPINFORM:   "INFORM",
}

# ---------------------------------------------------------------------------
# DHCP option codes
# ---------------------------------------------------------------------------
OPT_SUBNET_MASK         = 1
OPT_ROUTERS             = 3
OPT_DNS                 = 6
OPT_HOSTNAME            = 12
OPT_DOMAIN_NAME         = 15
OPT_BROADCAST           = 28
OPT_NTP                 = 42
OPT_VENDOR_ENCAPSULATED = 43   # option 43: PXE vendor encapsulated options
OPT_REQUESTED_IP        = 50
OPT_LEASE_TIME          = 51
OPT_MSG_TYPE            = 53
OPT_SERVER_ID           = 54
OPT_PARAM_REQUEST_LIST  = 55
OPT_RENEWAL_TIME        = 58
OPT_REBINDING_TIME      = 59
OPT_VENDOR_CLASS_ID     = 60
OPT_CLIENT_ID           = 61
OPT_TFTP_SERVER         = 66   # option 66: TFTP server name
OPT_BOOTFILE            = 67   # option 67: bootfile name
OPT_USER_CLASS          = 77
OPT_CLIENT_ARCH         = 93   # option 93: client architecture (PXE)
OPT_PXE_CLIENT_ID       = 97   # option 97: PXE UUID/GUID
OPT_DOMAIN_SEARCH       = 119  # option 119: domain search list (RFC 3397)

# PXE vendor suboption codes (used inside option 43)
PXE_DISCOVERY_CONTROL = 6
PXE_BOOT_SERVER       = 8
PXE_BOOT_MENU         = 9
PXE_MENU_PROMPT       = 10

DHCP_MAGIC_COOKIE = b"\x63\x82\x53\x63"
DHCP_SERVER_PORT  = 67
DHCP_CLIENT_PORT  = 68
BROADCAST_ADDR    = "255.255.255.255"


# ---------------------------------------------------------------------------
# Low-level encoding helpers
# ---------------------------------------------------------------------------

def _opt(code: int, data: bytes) -> bytes:
    """Encode a single TLV option."""
    return bytes([code, len(data)]) + data


def encode_ip(ip: str) -> bytes:
    return socket.inet_aton(ip)


def decode_ip(data: bytes) -> str:
    return socket.inet_ntoa(data[:4])


def encode_ip_list(ips: list) -> bytes:
    return b"".join(socket.inet_aton(ip) for ip in ips)


def encode_domain_search(domains: list) -> bytes:
    """Encode a domain search list per RFC 3397."""
    result = b""
    for domain in domains:
        for label in domain.rstrip(".").split("."):
            encoded = label.encode()
            result += bytes([len(encoded)]) + encoded
        result += b"\x00"
    return result


def encode_pxe_vendor_options(boot_menu: list = None) -> bytes:
    """
    Encode PXE vendor encapsulated options (content of option 43).
    boot_menu: list of (type_int, description_str) tuples, e.g. [(0, "Raspberry Pi Boot")]
    """
    payload = b""
    if boot_menu:
        for menu_type, description in boot_menu:
            desc_bytes = description.encode()
            item = struct.pack(">HB", menu_type, len(desc_bytes)) + desc_bytes
            payload += _opt(PXE_BOOT_MENU, item)
    payload += bytes([255])  # END suboption
    return payload


# ---------------------------------------------------------------------------
# DHCPPacket: parse incoming packets and build outgoing responses
# ---------------------------------------------------------------------------

@dataclass
class DHCPPacket:
    # Fixed BOOTP/DHCP header fields (RFC 2131 section 2)
    op:     int   = 1              # 1=BOOTREQUEST, 2=BOOTREPLY
    htype:  int   = 1              # hardware type (1=Ethernet)
    hlen:   int   = 6              # hardware address length
    hops:   int   = 0
    xid:    int   = 0              # transaction ID
    secs:   int   = 0
    flags:  int   = 0
    ciaddr: bytes = b"\x00" * 4   # client IP (if already bound)
    yiaddr: bytes = b"\x00" * 4   # your (offered) IP
    siaddr: bytes = b"\x00" * 4   # next-server IP (for TFTP)
    giaddr: bytes = b"\x00" * 4   # relay agent IP
    chaddr: bytes = b"\x00" * 16  # client hardware address (MAC + padding)
    sname:  bytes = b"\x00" * 64  # server host name (optional)
    file:   bytes = b"\x00" * 128 # boot file name
    options: dict = field(default_factory=dict)  # {code: bytes}

    # RPi MAC OUI prefixes
    RPI_OUIS = set(get_rpi_foundation_mac_vendor_ids())

    # Netgear MAC OUI prefixes
    NETGEAR_OUIS = set(get_netgear_mac_vendor_ids())

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    @classmethod
    def parse(cls, data: bytes) -> "DHCPPacket":
        if len(data) < 240:
            raise ValueError(f"Packet too short ({len(data)} bytes, expected >= 240)")
        pkt = cls()
        pkt.op     = data[0]
        pkt.htype  = data[1]
        pkt.hlen   = data[2]
        pkt.hops   = data[3]
        pkt.xid    = struct.unpack("!I",  data[4:8])[0]
        pkt.secs   = struct.unpack("!H",  data[8:10])[0]
        pkt.flags  = struct.unpack("!H",  data[10:12])[0]
        pkt.ciaddr = data[12:16]
        pkt.yiaddr = data[16:20]
        pkt.siaddr = data[20:24]
        pkt.giaddr = data[24:28]
        pkt.chaddr = data[28:44]
        pkt.sname  = data[44:108]
        pkt.file   = data[108:236]
        if data[236:240] != DHCP_MAGIC_COOKIE:
            raise ValueError("Missing DHCP magic cookie")
        pkt.options = cls._parse_options(data[240:])
        return pkt

    @staticmethod
    def _parse_options(data: bytes) -> dict:
        options = {}
        i = 0
        while i < len(data):
            code = data[i]
            if code == 0:    # PAD
                i += 1
                continue
            if code == 255:  # END
                break
            if i + 1 >= len(data):
                break
            length = data[i + 1]
            options[code] = data[i + 2: i + 2 + length]
            i += 2 + length
        return options

    # ------------------------------------------------------------------
    # Convenient read-only properties for incoming packet fields
    # ------------------------------------------------------------------

    @property
    def mac_address(self) -> str:
        """MAC address as lower-case colon-separated hex, e.g. 'b8:27:eb:a6:db:ab'."""
        return ":".join(f"{b:02x}" for b in self.chaddr[:self.hlen])

    @property
    def msg_type(self) -> Optional[int]:
        v = self.options.get(OPT_MSG_TYPE)
        return v[0] if v else None

    @property
    def requested_options(self) -> Optional[set[int]]:
        v = self.options.get(OPT_PARAM_REQUEST_LIST)
        if v is None:
            return None
        return set(v)

    def _get_str_option(self, opt) -> Optional[str]:
        val = self.options.get(opt)
        if val is None:
            return None
        try:
            return val.decode()
        except:
            return None

    @property
    def msg_type_name(self) -> str:
        return MSG_TYPE_NAMES.get(self.msg_type, f"UNKNOWN({self.msg_type})")

    @property
    def vendor_class_id(self) -> Optional[str]:
        """VCI string, e.g. 'PXEClient:Arch:00000:UNDI:002001'
           or 'walt.node.rpi-4-b'."""
        return self._get_str_option(OPT_VENDOR_CLASS_ID)

    @property
    def user_class_id(self) -> Optional[bytes]:
        """User class identifier"""
        return self._get_str_option(OPT_USER_CLASS)

    @property
    def client_arch(self) -> Optional[int]:
        """Client architecture (option 93): 0=x86, 6=EFI IA32, 7=EFI BC, 9=EFI x86-64."""
        v = self.options.get(OPT_CLIENT_ARCH)
        return struct.unpack("!H", v)[0] if v and len(v) >= 2 else None

    @property
    def pxe_client_id(self) -> Optional[bytes]:
        """16-byte PXE UUID/GUID from option 97 (leading type byte stripped)."""
        v = self.options.get(OPT_PXE_CLIENT_ID)
        return v[1:17] if v and len(v) >= 17 else None

    @property
    def cguid_repeated_serial(self) -> bool:
        """
        True if pxe-client-id looks like 4 repeated 4-byte serial numbers.
        This is the signature of RPi3B+ boards.
        """
        guid = self.pxe_client_id
        if not guid or len(guid) < 16:
            return False
        return guid[0:4] == guid[4:8] == guid[8:12] == guid[12:16]

    @property
    def requested_ip(self) -> Optional[str]:
        v = self.options.get(OPT_REQUESTED_IP)
        return decode_ip(v) if v else None

    @property
    def client_hostname(self) -> Optional[str]:
        v = self._get_str_option(OPT_HOSTNAME)
        return v.strip("\x00") if v else None

    @property
    def is_broadcast_requested(self) -> bool:
        return bool(self.flags & 0x8000)

    @property
    def is_pxe(self) -> bool:
        return (self.vendor_class_id or "").startswith("PXEClient")

    @property
    def is_rpi(self) -> bool:
        return self.mac_address[:8] in self.RPI_OUIS

    @property
    def is_x86(self) -> bool:
        return self.client_arch == 0

    @property
    def is_netgear(self) -> bool:
        return self.mac_address[:8] in self.NETGEAR_OUIS

    def wants_option(self, code: int) -> bool:
        requested_options = self.requested_options
        if requested_options is None:
            return True
        return code in requested_options

    # ------------------------------------------------------------------
    # Building reply packets
    # ------------------------------------------------------------------

    def new_reply(self, msg_type: int, offered_ip: str, server_ip: str,
                  lease_time: int = 6_000_000) -> "DHCPPacket":
        """
        Create a bare reply packet populated with mandatory fields.
        Add options with set_*() helpers before sending.
        """
        reply = DHCPPacket()
        reply.op     = 2  # BOOTREPLY
        reply.htype  = self.htype
        reply.hlen   = self.hlen
        reply.hops   = 0
        reply.xid    = self.xid
        reply.secs   = 0
        reply.flags  = self.flags
        reply.ciaddr = b"\x00" * 4
        reply.yiaddr = socket.inet_aton(offered_ip)
        reply.siaddr = socket.inet_aton(server_ip)   # next-server (TFTP)
        reply.giaddr = self.giaddr
        reply.chaddr = self.chaddr
        reply.options = {
            OPT_MSG_TYPE:   bytes([msg_type]),
            OPT_SERVER_ID:  socket.inet_aton(server_ip),
            OPT_LEASE_TIME: struct.pack("!I", lease_time),
            OPT_RENEWAL_TIME:   struct.pack("!I", lease_time // 2),
            OPT_REBINDING_TIME: struct.pack("!I", lease_time * 7 // 8),
        }
        return reply

    def set_option_if_requested(self, request: "DHCPPacket", code: int, data: bytes):
        if request.wants_option(code):
            self.options[code] = data

    def set_network_options(self, request: "DHCPPacket", subnet: str, broadcast: str,
                            routers: list, dns: list,
                            domain: str, ntp: list = None):
        """Set standard network options on this (reply) packet."""
        self.set_option_if_requested(request, OPT_SUBNET_MASK, encode_ip(subnet))
        self.set_option_if_requested(request, OPT_BROADCAST, encode_ip(broadcast))
        if len(routers) > 0:
            self.set_option_if_requested(request, OPT_ROUTERS, encode_ip_list(routers))
        self.set_option_if_requested(request, OPT_DNS, encode_ip_list(dns))
        self.set_option_if_requested(request, OPT_DOMAIN_NAME, domain.encode())
        self.set_option_if_requested(
            request, OPT_DOMAIN_SEARCH, encode_domain_search([domain])
        )
        if ntp:
            self.set_option_if_requested(request, OPT_NTP, encode_ip_list(ntp))

    def set_hostname(self, request: "DHCPPacket", hostname: str):
        self.set_option_if_requested(request, OPT_HOSTNAME, hostname.encode())

    def set_tftp_options(self, server_ip: str, filename: str = None):
        """Set TFTP server name (option 66) and optional boot filename (option 67)."""
        self.options[OPT_TFTP_SERVER] = server_ip.encode()
        if filename:
            self.options[OPT_BOOTFILE] = filename.encode()
            # Also fill the legacy BOOTP 'file' field for maximum compatibility
            self.file = filename.encode().ljust(128, b"\x00")[:128]

    def set_pxe_rpi_options(self, boot_menu_text: str = "Raspberry Pi Boot"):
        """Set vendor-class-identifier and option 43 for native RPi PXE boot."""
        self.options[OPT_VENDOR_CLASS_ID]     = b"PXEClient"
        self.options[OPT_VENDOR_ENCAPSULATED] = encode_pxe_vendor_options(
            boot_menu=[(0, boot_menu_text)]
        )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_bytes(self) -> bytes:
        data = bytes([self.op, self.htype, self.hlen, self.hops])
        data += struct.pack("!I",  self.xid)
        data += struct.pack("!HH", self.secs, self.flags)
        data += self.ciaddr + self.yiaddr + self.siaddr + self.giaddr
        data += self.chaddr[:16].ljust(16, b"\x00")
        data += self.sname[:64].ljust(64,   b"\x00")
        data += self.file[:128].ljust(128,  b"\x00")
        data += DHCP_MAGIC_COOKIE
        data += self._encode_options()
        return data

    def _encode_options(self) -> bytes:
        result = b""
        for code, value in self.options.items():
            result += _opt(code, value)
        result += bytes([255])  # END
        return result

    def print(self, **info):
        log_msg = f"[{self.msg_type_name}] mac={self.mac_address}"
        for k, v in info.items():
            if v is not None:
                log_msg += f" {k}={v!r}"
        print(log_msg)

# ---------------------------------------------------------------------------
# DHCPServer: socket management
# ---------------------------------------------------------------------------

class DHCPServer:
    """
    Base DHCP server. Bind to a specific network interface on port 67.
    Subclass and override handle_packet() to implement policy.
    """

    def __init__(self, interface: str, server_ip: str):
        self.interface = interface
        self.server_ip = server_ip
        self._sock = None

    def init_socket(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        # Bind to a specific interface so we don't capture traffic meant
        # for other DHCP servers running on other interfaces.
        self._sock.setsockopt(
            socket.SOL_SOCKET, socket.SO_BINDTODEVICE,
            self.interface.encode()
        )
        self._sock.bind(("", DHCP_SERVER_PORT))
        print(f"WALT DHCP server now listening on {self.interface}")

    def fileno(self):
        return self._sock.fileno()

    def handle_event(self, ts):
        data, addr = self._sock.recvfrom(4096)
        pkt = DHCPPacket.parse(data)
        self.handle_packet(pkt)

    def close(self):
        self._sock.close()

    def send(self, reply: DHCPPacket):
        """
        Send a reply packet, respecting relay agent and broadcast rules
        per RFC 2131 section 4.1.
        """
        data = reply.to_bytes()
        if reply.giaddr != b"\x00" * 4:
            # Relay agent present: unicast back to the relay on server port
            dest = (decode_ip(reply.giaddr), DHCP_SERVER_PORT)
        elif reply.is_broadcast_requested or reply.ciaddr == b"\x00" * 4:
            # Client has no IP yet, or explicitly requested broadcast
            dest = (BROADCAST_ADDR, DHCP_CLIENT_PORT)
        else:
            dest = (decode_ip(reply.ciaddr), DHCP_CLIENT_PORT)
        self._sock.sendto(data, dest)

    def handle_packet(self, pkt: DHCPPacket):
        """Override in subclass to implement DHCP policy."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# WALT DHCP handler
# ---------------------------------------------------------------------------

class WaltDHCPServer(DHCPServer):
    """
    DHCPServer subclass implementing WalT logic.
    """

    # Network parameters
    SUBNET_MASK = str(WALT_SUBNET.netmask)
    BROADCAST   = str(WALT_SUBNET.broadcast_address)
    ROUTERS     = [WALT_SERVER_IP]
    DNS         = [WALT_SERVER_IP]
    NTP         = [WALT_SERVER_IP]
    DOMAIN      = "walt"
    LEASE_TIME  = 6_000_000

    def __init__(self, engine):
        self._engine = engine
        DHCPServer.__init__(self, "walt-net", WALT_SERVER_IP)

    # ------------------------------------------------------------------
    # Packet handling
    # ------------------------------------------------------------------

    def handle_packet(self, pkt: DHCPPacket):
        mac = pkt.mac_address
        msg = pkt.msg_type
        # Only process DISCOVER and REQUEST; ignore the rest for now
        if msg == DHCPDISCOVER:
            self._handle_discover(pkt)
        elif msg == DHCPREQUEST:
            self._handle_request(pkt)
        elif msg == DHCPRELEASE:
            print(f"  RELEASE from {mac}, ignoring (fixed leases)")

    def _get_routers(self, pkt: DHCPPacket):
        if self._engine.should_add_routers(pkt):
            return self.ROUTERS
        else:
            return []

    def _offer_or_ack(self, msg_type: int, pkt: DHCPPacket, ip: str):
        reply = pkt.new_reply(msg_type, ip, self.server_ip, self.LEASE_TIME)
        reply.set_network_options(
            pkt,
            self.SUBNET_MASK, self.BROADCAST,
            self._get_routers(pkt),
            self.DNS, self.DOMAIN, self.NTP,
        )
        if pkt.is_pxe:
            self._engine.apply_pxe_options(pkt, reply)
        name = self._engine.get_name_for_ip(ip)
        if name:
            reply.set_hostname(pkt, name)
        self.send(reply)
        return reply

    def _offer(self, pkt: DHCPPacket, ip: str):
        reply = self._offer_or_ack(DHCPOFFER, pkt, ip)
        reply.print(ip=ip)

    def _ack(self, pkt: DHCPPacket, ip: str):
        reply = self._offer_or_ack(DHCPACK, pkt, ip)
        reply.print()

    def _nak(self, pkt: DHCPPacket):
        reply = pkt.new_reply(DHCPNAK, "0.0.0.0", self.server_ip, 0)
        reply.print()
        self.send(reply)

    def _handle_discover(self, pkt: DHCPPacket):
        ip = self._engine.process_discover(pkt)
        if ip is None:
            return
        self._offer(pkt, ip)

    def _handle_request(self, pkt: DHCPPacket):
        ip = self._engine.process_request(pkt)
        if ip is None:
            self._nak(pkt)
            return
        self._ack(pkt, ip)


class DHCPdUnixListener:
    def __init__(self, engine, req, **params):
        self._engine = engine
        self._req = req

    def run(self, s, peer_addr, *args):
        if self._req == "RELOAD_CONF":
            self._engine.reload_conf()
            s.sendto(b"OK", peer_addr)
        elif self._req == "HEARTBEAT":
            self._engine.heartbeat()
            s.sendto(b"OK", peer_addr)
        elif self._req == "ALLOCATE_IP":
            mac = args[0]
            ip = self._engine.allocate_ip(mac)
            if ip is None:
                s.sendto(b"FAILED no more IP in WALT subnet!", peer_addr)
            else:
                s.sendto(b"OK " + ip.encode(), peer_addr)


class WalTDHCPdEngine:
    def __init__(self, ev_loop):
        self._ev_loop = ev_loop
        # start listening UDP only when reload_conf() has been called
        # at least once
        self._loaded_conf = False
        # start with an outdated heartbeat timestamp: if we receive
        # a new DISCOVER message before the first heartbeat of main
        # daemon, then we enter the degraded mode right away.
        self._last_walt_heartbeat = 0
        self._curr_degraded_mode = False

    def check_degraded_mode(self):
        """Check if last heartbeat sent by main daemon is outdated."""
        degraded_mode = (time() >
            self._last_walt_heartbeat + DHCPD_HEARTBEAT_PERIOD + 1)
        if degraded_mode and not self._curr_degraded_mode:
            print("** Entered degraded mode: "
                  "outdated heartbeat from main daemon.")
        self._curr_degraded_mode = degraded_mode
        return degraded_mode

    def heartbeat(self):
        self._last_walt_heartbeat = time()
        if self._curr_degraded_mode:
            print("** Recovered from degraded mode: "
                  "new heartbeat from main daemon.")
            self._free_ips |= set(self._degraded_ip_per_devmac.values())
            self._degraded_ip_per_devmac = {}
            self._curr_degraded_mode = False
            self._print_leases()

    def _print_leases(self):
        if DEBUG_LEASES:
            print(   f"-- leases {len(self._ip_per_devmac):>6} std")
            if len(self._tmp_ip_per_ip) > 0:
                print(f"          {len(self._tmp_ip_per_ip):>6} "
                      f"tmp      -- {self._tmp_ip_per_ip!r}")
            if len(self._degraded_ip_per_devmac) > 0:
                print(f"          {len(self._degraded_ip_per_devmac):>6} "
                      f"degraded -- {self._degraded_ip_per_devmac!r}")

    def reload_conf(self):
        new_devices = pickle.loads(DHCPD_DEVICES_FILE.read_bytes())
        if not self._loaded_conf:
            # first conf loading
            self._tmp_ip_per_ip = {}
            self._degraded_ip_per_devmac = {}
            self._update_conf(new_devices)
            print(f"** Loaded {DHCPD_DEVICES_FILE}")
            self._loaded_conf = True
            # create UDP management service and add it to the event loop
            udp_server = WaltDHCPServer(self)
            udp_server.init_socket()
            self._ev_loop.register_listener(udp_server)
        else:
            self._update_conf(new_devices)
            print(f"** Reloaded {DHCPD_DEVICES_FILE}")
        self._print_leases()

    def _update_conf(self, devices):
        netsetup_mask = (devices.netsetup == 1)
        self._routed_devmacs = set(devices[netsetup_mask].mac)
        self._name_per_ip = dict(devices[["ip", "name"]])
        self._type_per_devmac = dict(devices[["mac", "type"]])
        vpn_mask = devices.vpnmac.nonzero()[0]
        self._devmac_per_vpnmac = dict(devices[vpn_mask][["vpnmac", "mac"]])
        self._ip_per_devmac = dict(devices[["mac", "ip"]])
        self._cleanup_obsolete_tmp_ips(devices)
        self._compute_free_ips(devices)

    def _cleanup_obsolete_tmp_ips(self, devices):
        if len(self._tmp_ip_per_ip) > 0:
            nodes_mask = (devices.type == "node")
            node_ips = set(devices[nodes_mask].ip)
            ips_with_tmp_ip = set(self._tmp_ip_per_ip.keys())
            for ip in node_ips & ips_with_tmp_ip:
                # the device has completed its transition to
                # type="node", we no longer need the temporary IP
                # we used
                self._tmp_ip_per_ip.pop(ip)

    def _compute_free_ips(self, devices):
        self._free_ips = set(str(ip) for ip in WALT_SUBNET.hosts())
        self._free_ips -= {WALT_SERVER_IP}
        self._free_ips -= set(devices.ip)
        self._free_ips -= set(self._tmp_ip_per_ip.values())
        self._free_ips -= set(self._degraded_ip_per_devmac.values())

    def _get_devmac(self, msgmac):
        devmac = self._devmac_per_vpnmac.get(msgmac)
        if devmac is None:
           # message mac is not a VPN mac, so it's a device mac
           devmac = msgmac
        return devmac

    def should_add_routers(self, pkt: DHCPPacket) -> bool:
        msgmac = pkt.mac_address
        devmac = self._get_devmac(msgmac)
        if devmac in self._routed_devmacs:
            return True
        # Raspberry Pi 5 HTTP boot fails if no "Routers" DHCP option
        # is returned (even if the boot server IP is the WALT server,
        # in the same subnet). So add it anyway in this case.
        detected_type, model, hints = self._detect_type_and_model(pkt)
        if hints.get("boot-mode", None) == "vpn-http":
            return True
        return False

    def get_name_for_ip(self, ip):
        return self._name_per_ip.get(ip)

    def process_discover(self, pkt: DHCPPacket) -> Optional[str]:
        """Process DISCOVER, notify main daemon, return IP or None"""
        degraded_mode = self.check_degraded_mode()
        detected_type, model, hints = self._detect_type_and_model(pkt)
        pkt.print(type=detected_type, model=model, **hints)
        msgmac = pkt.mac_address
        devmac = self._get_devmac(msgmac)
        registered_type = self._type_per_devmac.get(devmac)
        new_lease = False
        error = False
        if registered_type is not None:
            # device already known by main daemon
            if degraded_mode and registered_type == "node":
                # in degraded mode, we allocate temporary IPs to nodes
                # in order to let them target the boot-loop files
                ip = self._degraded_ip_per_devmac.get(devmac)
                if ip is None:
                    ip = self.allocate_ip()
                    if ip is None:
                        print(f"  No IP available for {msgmac}, "
                              "dropping DISCOVER")
                        return None  # failed
                    self._degraded_ip_per_devmac[devmac] = ip
                    self._print_leases()
            else:
                ip = self._ip_per_devmac[devmac]
            new = False
        else:
            # device not yet known by main daemon
            ip = self._ip_per_devmac.get(devmac)
            if ip is None:
                ip = self.allocate_ip(devmac)
                if ip is None:
                    print(f"  No IP available for {msgmac}, "
                          "dropping DISCOVER")
                    return None  # failed
                new_lease = True
                self._print_leases()
            new = True
        # Notes:
        # - We detect and notify new devices as soon as we get the
        #   DISCOVER message.
        #   Otherwise, it would fail in the case of RPi3B+, because of a
        #   board firmware bug: it boots after OFFER without sending REQUEST.
        # - We only notify the main daemon when the device is new or
        #   its type was "unknown" and this new DISCOVER message allowed
        #   to identify it.
        selected_ip = ip
        if new or (registered_type == "unknown" and
                   detected_type != "unknown"):
            if degraded_mode:
                print("  Cannot handle new nodes or devices in degraded "
                      "mode, dropping DISCOVER")
                error = True
            else:
                selected_ip = self._notify_new_device(
                        msgmac, devmac, ip, pkt.client_hostname,
                        detected_type, model)
                if selected_ip is None:
                    error = True  # failed
        if error:
            # failed, undo whatever we did above
            if new_lease:
                ip = self._ip_per_devmac.pop(devmac)
                self._free_ips.add(ip)
                self._print_leases()
            return None  # failed
        return selected_ip

    def process_request(self, pkt: DHCPPacket) -> Optional[str]:
        pkt.print(requested_ip = pkt.requested_ip)
        msgmac = pkt.mac_address
        devmac = self._get_devmac(msgmac)
        # degraded mode case
        ip = self._degraded_ip_per_devmac.get(devmac)
        if ip == pkt.requested_ip:
            return ip
        # regular mode
        ip = self._ip_per_devmac.get(devmac)
        if ip == pkt.requested_ip:
            return ip
        # node registration procedure
        ip = self._tmp_ip_per_ip.get(ip)
        if ip == pkt.requested_ip:
            return ip
        print("Unexpected IP requested!")
        return None

    def allocate_ip(self, mac: Optional[str] = None) -> Optional[str]:
        """Allocate an IP, update self._ip_per_devmac if mac provided."""
        if len(self._free_ips) == 0:
            return None
        ip = self._free_ips.pop()
        if mac:
            self._ip_per_devmac[mac] = ip
        return ip

    def _notify_new_device(self, msgmac: str, devmac: str, ip: str,
                           devname: Optional[str],
                           detected_type: str, model: Optional[str]):
        """Notify the main WALT service about a new or updated device."""
        if devname:
            # add suffix with end of mac
            mac_suffix = "".join(devmac.split(":"))[-6:]
            if not devname.endswith(mac_suffix):
                devname = f"{devname}-{mac_suffix}".lower()
        kwargs = dict(
                mac = devmac,
                ip = ip,
                type = detected_type,
                model = model,
                name = devname,
        )
        # When transitioning from type="unknown" to type="node",
        # (including the time the main daemon may need to download
        # the default OS image of a new node), we change the device
        # IP address to avoid inconsistencies between the two sets of
        # boot files involved (boot files involved in the boot loop vs
        # boot files embedded in the default OS image): during the boot
        # procedure of a board, all TFTP requests must obviously target
        # the same set of boot files.
        if detected_type == "node":
            tmp_ip = self._tmp_ip_per_ip.get(ip)
            if tmp_ip is None:
                tmp_ip = self.allocate_ip()
                if tmp_ip is None:
                    print(f"  No IP available for {msgmac}, "
                          "dropping DISCOVER")
                    return None  # failed
                self._tmp_ip_per_ip[ip] = tmp_ip
                self._print_leases()
            kwargs.update(
                tmp_ip = tmp_ip,
            )
        with ServerAPILink("localhost", "SSAPI") as server:
            used_ip = server.register_device(**kwargs)
        return used_ip  # succeeded

    def apply_pxe_options(self, pkt: DHCPPacket, reply: DHCPPacket):
        """Add PXE-specific options to a reply based on what the client is."""
        if pkt.is_rpi:
            reply.set_pxe_rpi_options()
        elif pkt.is_x86:
            uci = pkt.user_class_id or ""
            if uci.startswith("walt.node"):
                # iPXE 2nd stage --
                # We get here when walt-x86-undionly.kpxe is running on
                # the node. The VCI is still the one of PXE, but the UCI
                # has been modified to indicate a walt node.
                # The binary specifies itself the script to boot from TFTP,
                # so no bootfile option is needed here.
                pass
            else:
                # iPXE 1st stage
                reply.set_tftp_options(self.server_ip,
                                       "pxe/walt-x86-undionly.kpxe")

    def _detect_type_and_model(self, pkt: DHCPPacket):
        # for device types on which we install a custom network bootloader,
        # the VCI (u-boot) or UCI (ipxe) field of DHCP DISCOVER messages
        # is set to "walt.node.<model>".
        for class_id in (pkt.vendor_class_id, pkt.user_class_id):
            if class_id is None:
                continue
            if class_id.startswith("walt.node."):
                return "node", class_id[10:], {}
        # We also detect netgear switches
        if pkt.is_netgear:
            return "switch", "netgear", {}
        # The firmware of rpi-3-b-plus boards repeats 4 times the board
        # serial in the cguid field.
        # With more recent Raspberry Pi firmware, DHCP option 97
        # (aka PXE client UUID/GUID) starts with 'RPi4' (0x34695052)
        # or 'RPi5' 0x35695052.
        # (https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#DHCP_OPTION97)
        if pkt.is_pxe:
            if pkt.is_rpi:
                cguid = pkt.pxe_client_id
                if cguid is not None:
                    if cguid.startswith(b'5iPR'):
                        if pkt.wants_option(OPT_VENDOR_ENCAPSULATED):
                            boot_mode = "tftp"
                        else:
                            boot_mode = "vpn-http"
                        return "node", "rpi-5-b", {"boot-mode": boot_mode}
                    if cguid.startswith(b'4iPR'):
                        return "node", "rpi-4-b", {}
                    if (len(cguid) >= 16 and
                        (cguid[0:4] == cguid[4:8] ==
                         cguid[8:12] == cguid[12:16])):
                        return "node", "rpi-3-b-plus", {}
        # unknown device, return a few hints
        hints = {}
        if pkt.is_pxe:
            hints.update(pxe="true")
        else:
            hints.update(vci=pkt.vendor_class_id)
        if pkt.is_rpi:
            hints.update(rpi="true")
        hints.update(uci=pkt.user_class_id,
                     cguid=pkt.pxe_client_id)
        return "unknown", None, hints


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def run():
    # create DHCPd engine and event loop
    ev_loop = EventLoop()
    engine = WalTDHCPdEngine(ev_loop)
    # init engine if the devices file exists
    if DHCPD_DEVICES_FILE.exists():
        engine.reload_conf()
    else:
        print("Waiting for the main daemon to update the configuration.")
    # create the unix ctrl socket listener and add it to the event loop
    unix_server = UnixServer(DHCPD_CTRL_SOCK_PATH)
    for req_id in ("RELOAD_CONF", "HEARTBEAT", "ALLOCATE_IP"):
        unix_server.register_listener_class(
                req_id=req_id,
                cls=DHCPdUnixListener,
                engine=engine,
                req=req_id)
    unix_server.prepare(ev_loop)
    # notify systemd that we are ready
    notify_systemd()
    # start the event loop
    try:
        ev_loop.loop()
    except KeyboardInterrupt:
        print()
        print("Aborted.")
        return
