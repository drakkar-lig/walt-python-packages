import itertools
import time
from collections import defaultdict

from snimpy.snmp import SNMPException
from walt.common.formatting import format_sentence, human_readable_delay
from walt.server import const, snmp
from walt.server.processes.blocking.devices.grouper import (
        Grouper,
        AlreadyGroupedException,
)
from walt.server.processes.blocking.devices.loops import LoopsSolver
from walt.server.processes.blocking.devices.tree import Tree
from walt.server.snmp import NoSNMPVariantFound
from walt.server.snmp.lldp import (
        get_port_number_from_lldp_label,
        save_lldp_label_for_port_number,
)
from walt.server.tools import get_server_ip, ip_in_walt_adm_network, ip_in_walt_network

NOTE_EXPLAIN_UNREACHABLE = (
    "devices marked with parentheses were not detected at last scan"
)
NOTE_EXPLAIN_UNKNOWN = "type of devices marked with <? ... ?> is unknown"

TIP_ADD_FLAG_ALL = "use 'walt device tree --all' to see all devices detected"
TIP_DEVICE_SHOW = "use 'walt device show' for device details"
TIP_DEVICE_RESCAN = "use 'walt device rescan' to update"
TIP_DEVICE_ADMIN_1 = (
    "use 'walt device config <device> type=switch'"
    " to let WalT know a given device is a switch"
)
TIP_DEVICE_ADMIN_2 = (
    "use 'walt device config ...' (see walt help show device-config)"
    " to let WalT explore forbidden switches"
)
TIP_DEVICE_ADMIN_3 = (
    "use 'walt device port-config ...' (see walt help show device-port-config)"
    " to give sensible names to switch ports"
)
TIPS_MIN = (TIP_DEVICE_SHOW, TIP_DEVICE_ADMIN_2, TIP_DEVICE_ADMIN_3, TIP_DEVICE_RESCAN)

NOTE_LAST_NETWORK_SCAN = (
    "this view comes from last network scan, issued %s ago"
    " (use 'walt device rescan' to update)"
)

NOTE_LAST_NETWORK_SCAN_UNKNOWN = (
    "this view comes from last network scan (use 'walt device rescan' to update)"
)

MSG_NO_NEIGHBORS = """\
WalT Server did not detect any neighbor!
"""
MSG_UNKNOWN_TOPOLOGY = """\
Sorry, topology is unknown. Ensure a switch is connected to server \
(on walt-net interface) and run "walt device rescan".
"""


def format_explanation(item_type, items):
    if len(items) == 0:
        return ""
    if len(items) == 1:
        return item_type + ": " + items[0] + ".\n"
    return item_type + "s:" + "".join("\n- " + item for item in items) + "\n"


def get_unique_value(s):
    return next(iter(s))


def two_levels_dict_browse(d):
    for k1, v1 in d.items():
        for k2, v2 in v1.items():
            yield k1, k2, v2


class BridgeTopology:
    def __init__(self, vpnmac_to_mac):
        self.secondary_to_main_mac = vpnmac_to_mac
        self.candidate_macs_per_port = defaultdict(set)

    def register_secondary_macs(self, sw_mac, secondary_macs):
        """Register secondary mac addresses of a switch"""
        secondary_macs -= set((sw_mac,))
        self.secondary_to_main_mac.update({mac: sw_mac for mac in secondary_macs})

    def register_neighbor(self, local_mac, local_port, neighbor_mac):
        """Register a neighbor of the forwarding table"""
        # This is a neighbor of the forwarding table, thus we may have
        # many of them on a single switch port.
        self.candidate_macs_per_port[(local_mac, local_port)].add(neighbor_mac)

    def add_ll_confirmed_data(self, ll_topology):
        """Add lldp topology data to this bridge"""
        # Adding LLDP data to this bridge topology helps getting a better analysis,
        # for instance regarding the fact the server only replies to LLDP queries.
        # Having an LLDP record (server_mac, server_port) -> main_switch_mac
        # is an interesting information we would miss otherwise.
        # The bridge data of the main_switch will be:
        # (main_switch_mac, main_switch_port) -> many macs including server_mac
        # because of the various virtual mac addresses on the server (vnodes, etc.)
        # Having the LLDP record, the deduce_link_layer_topology() method below
        # will deduce that the two-way link is:
        # (server_mac, server_port) <-> (main_switch_mac, main_switch_port)
        # Otherwise, the main_switch_port information would be lost.
        for mac1, mac2, port1, port2, confirmed, last_seen in ll_topology:
            if confirmed:
                if port1 is not None:
                    self.register_neighbor(mac1, port1, mac2)
                if port2 is not None:
                    self.register_neighbor(mac2, port2, mac1)

    def deduce_link_layer_topology(self, db):
        """Analyse the forwarding table to deduce the link layer topology"""
        # First steps:
        # * replace secondary macs of switches with their main mac
        # * filter-out mac addresses missing in db (unlike LLDP, we cannot
        #   insert these missing devices in db because we don't know their ip)
        # * compute a 'backbone' view reduced to the links between the switches or
        #   the server
        # * compute an 'edge' view reduced to the links between a switch
        #   and an edge device
        db_types = {dev.mac: dev.type for dev in db.select("devices")}
        db_macs = set(db_types.keys())
        db_backbone_macs = set(
            mac for mac, t in db_types.items() if t in ("switch", "server")
        )
        backbone_candidate_macs_per_port = defaultdict(lambda: defaultdict(set))
        edge_candidate_macs_per_port = defaultdict(lambda: defaultdict(set))
        for sw_port_info, macs in self.candidate_macs_per_port.items():
            macs = set(self.secondary_to_main_mac.get(mac, mac) for mac in macs)
            macs = macs.intersection(db_macs)
            backbone_macs = macs.intersection(db_backbone_macs)
            edge_macs = macs - backbone_macs
            sw_mac, sw_port = sw_port_info
            if len(backbone_macs) > 0:
                backbone_candidate_macs_per_port[sw_mac][sw_port] = backbone_macs
            if len(edge_macs) > 0:
                edge_candidate_macs_per_port[sw_mac][sw_port] = edge_macs
        # We first analyse the backbone topology.
        changed = False
        while not changed:
            # We invert backbone_candidate_macs_per_port to know on which switch ports
            # a given device is possibly connected.
            # (cf. backbone_candidate_ports_per_mac)
            backbone_candidate_ports_per_mac = defaultdict(set)
            for sw_mac, sw_port, macs in two_levels_dict_browse(
                backbone_candidate_macs_per_port
            ):
                for mac in macs:
                    backbone_candidate_ports_per_mac[mac].add((sw_mac, sw_port))
            # let's consider a device D reported both on port a of switch A and on port
            # b of switch B. if switch B is reported on a port a' (different from a) on
            # switch A, then we know that switch A is closer to device D than switch B.
            candidate_macs_per_port = defaultdict(lambda: defaultdict(set))
            for mac_D, candidate_sw_ports in backbone_candidate_ports_per_mac.items():
                for switch_A_port, switch_B_port in itertools.permutations(
                    candidate_sw_ports, 2
                ):
                    mac_A, a = switch_A_port
                    mac_B, b = switch_B_port
                    a_prim = None
                    for mac, port in backbone_candidate_ports_per_mac.get(mac_B, ()):
                        if mac == mac_A:
                            a_prim = port
                            if a_prim != a:
                                backbone_candidate_macs_per_port[mac_B][b] -= set(
                                    (mac_D,)
                                )
                                changed = True
                            break
            if changed:
                continue
            # if switch A has a unique candidate on port a which is switch B,
            # then if switch A is reported on any port b of switch B,
            # replace the list of candidates there by switch A only.
            match = False
            for mac_A, a, candidate_macs in two_levels_dict_browse(
                backbone_candidate_macs_per_port
            ):
                if len(candidate_macs) == 1:
                    mac_B = get_unique_value(candidate_macs)
                    ports_B = backbone_candidate_macs_per_port.get(mac_B, {})
                    for b, candidate_macs in ports_B.items():
                        if mac_A in candidate_macs:
                            # if switch A is already the unique candidate,
                            # there is nothing to change
                            if len(candidate_macs) != 1:
                                match = True
                            break
                if match:
                    break
            if match:
                backbone_candidate_macs_per_port[mac_B][b] = set((mac_A,))
                changed = True
            if not changed:
                break  # nothing changed during last iteration, exit loop
        # We now build ll_topology considering switch ports with only one candidate mac.
        # Edge devices reported on the ports of the backbone are ignored.
        # (We actually process them first so that they are overridden in this case)
        ll_topology = LinkLayerTopology({})
        for candidate_macs_per_port in (
            edge_candidate_macs_per_port,
            backbone_candidate_macs_per_port,
        ):
            for sw_mac, sw_port, candidate_macs in two_levels_dict_browse(
                candidate_macs_per_port
            ):
                if len(candidate_macs) == 1:
                    mac = get_unique_value(candidate_macs)
                    ll_topology.register_neighbor(sw_mac, sw_port, mac)
        return ll_topology


class LinkLayerTopology(object):
    def __init__(self, vpnmac_to_mac):
        # links as a dict (mac1, mac2) -> (port1, port2, confirmed, last_seen)
        self.links = {}
        self.secondary_to_main_mac = vpnmac_to_mac

    def is_empty(self):
        return len(self.links) == 0

    def locate_mac(self, mac):
        for link_macs, link_info in self.links.items():
            if mac == link_macs[0]:
                return link_macs[1], link_info[1], link_info[2]
            if mac == link_macs[1]:
                return link_macs[0], link_info[0], link_info[2]
        return None, None, None

    def discard_link(self, mac1, mac2):
        mac1, mac2 = sorted((mac1, mac2))
        self.links.pop((mac1, mac2), None)

    def register_neighbor(self, local_mac, local_port, neighbor_mac):
        now = time.time()
        local_mac = self.secondary_to_main_mac.get(local_mac, local_mac)
        neighbor_mac = self.secondary_to_main_mac.get(neighbor_mac, neighbor_mac)
        mac1, mac2 = sorted((local_mac, neighbor_mac))
        link = self.links.get((mac1, mac2))
        if link is None:
            # first time we see this link
            if local_mac < neighbor_mac:
                port1, port2 = local_port, None
            else:
                port1, port2 = None, local_port
            self.links[(mac1, mac2)] = port1, port2, True, now
        else:
            # update port on existing link
            if local_mac < neighbor_mac:
                self.links[(mac1, mac2)] = local_port, link[1], True, now
            else:
                self.links[(mac1, mac2)] = link[0], local_port, True, now

    def load_from_db(self, db):
        sql = ( "SELECT "
                    "mac1, mac2, port1, port2, confirmed, "
                    "EXTRACT(EPOCH FROM last_seen)::float8 as last_seen "
                "FROM topology;")
        for db_link in db.execute(sql):
            self.links[(db_link.mac1, db_link.mac2)] = (
                db_link.port1,
                db_link.port2,
                db_link.confirmed,
                db_link.last_seen,
            )

    def save_to_db(self, db):
        db.delete("topology")
        for link_macs, link_info in self.links.items():
            db.execute(("INSERT INTO topology("
                            "mac1, mac2, port1, "
                            "port2, confirmed, last_seen) "
                        "VALUES (%s, %s, %s, %s, %s, TO_TIMESTAMP(%s));"),
                       link_macs + link_info)
        db.commit()

    def set_confirm_all(self, value):
        for k, v in self.links.copy().items():
            if v[2] != value:
                new_v = v[:2] + (value,) + (v[3],)
                self.links[k] = new_v

    def unconfirm(self, devices):
        new_links = {}
        # any device connected to one of the specified
        # switches or server should now have its 'confirmed' flag
        # set to false.
        device_macs = set(dev.mac for dev in devices)
        for k, v in self.links.copy().items():
            if v[2] is True and len(set(k) & device_macs) > 0:
                unconfirmed_v = v[:2] + (False,) + (v[3],)
                self.links[k] = unconfirmed_v

    def __iter__(self):
        # iterate over links info
        for macs, info in self.links.copy().items():
            yield macs + info  # concatenate the tuples

    def merge_links_info(self, trusted, untrusted):
        port1 = untrusted[0] if trusted[0] is None else trusted[0]
        port2 = untrusted[1] if trusted[1] is None else trusted[1]
        return port1, port2, trusted[2], trusted[3]

    def merge_other(self, other):
        # build the union of 'self.links' and 'other.links';
        # in case of conflict, merge information, giving
        # priority to confirmed links and recent last_seen attribute.
        new_links = {}
        keys_self = set(self.links)
        keys_other = set(other.links)
        common_keys = keys_self & keys_other
        for k in common_keys:
            if self.links[k][2:] < other.links[k][2:]:
                trusted, untrusted = other.links[k], self.links[k]
            else:
                trusted, untrusted = self.links[k], other.links[k]
            new_links[k] = self.merge_links_info(trusted, untrusted)
        for k in keys_self - keys_other:
            new_links[k] = self.links[k]
        for k in keys_other - keys_self:
            new_links[k] = other.links[k]
        # check if we have several links at the same location
        # (mac, non-null-port), and in this case keep the one
        # with highest priority.
        locations = {}
        no_loc = (None, None)
        for macs, info in new_links.copy().items():
            mac1, mac2, port1, port2 = macs + info[:2]
            prio = info[2:]
            if port1 is not None:
                conflict_mac2, conflict_prio = locations.get((mac1, port1), no_loc)
                if conflict_mac2 is not None:
                    if prio > conflict_prio:  # higher prio, discard the old one
                        new_links.pop((mac1, conflict_mac2), None)
                        locations[(mac1, port1)] = (mac2, prio)
                    else:  # lower prio, discard this one
                        new_links.pop((mac1, mac2), None)
                else:
                    locations[(mac1, port1)] = (mac2, prio)
            if port2 is not None:
                conflict_mac1, conflict_prio = locations.get((mac2, port2), no_loc)
                if conflict_mac1 is not None:
                    if prio > conflict_prio:  # higher prio, discard the old one
                        new_links.pop((conflict_mac1, mac2), None)
                        locations[(mac2, port2)] = (mac1, prio)
                    else:  # lower prio, discard this one
                        new_links.pop((mac1, mac2), None)
                else:
                    locations[(mac2, port2)] = (mac1, prio)
        self.links = new_links

    def cleanup(self, nodes_mac):
        # This procedure will remove obsolete links from moved devices,
        # and ensure we have no loops.
        # As a first criterion, we consider that nodes cannot have more
        # than 1 neighbor in the topology.
        found_nodes = {}
        for macs, info in self.links.copy().items():
            mac1, mac2, port1, port2 = macs + info[:2]
            prio = info[2:]
            is_node = (mac1 in nodes_mac), (mac2 in nodes_mac)
            if is_node[0] and is_node[1]:  # 1 and 2 are nodes ??
                # strange, should not have a link between two nodes
                self.links.pop((mac1, mac2), None)
                continue
            if is_node[0]:  # dev 1 is a node
                if mac1 in found_nodes:
                    # node 1 cannot be connected at 2 different places
                    prev_mac2, prev_prio = found_nodes[mac1]
                    if prio > prev_prio:  # higher prio, discard the old one
                        self.links.pop(tuple(sorted((mac1, prev_mac2))), None)
                        found_nodes[mac1] = (mac2, prio)
                    else:  # lower prio, discard this one
                        self.links.pop((mac1, mac2), None)
                else:
                    found_nodes[mac1] = (mac2, prio)
                continue
            if is_node[1]:  # dev 2 is a node
                if mac2 in found_nodes:
                    # node 2 cannot be connected at 2 different places
                    prev_mac1, prev_prio = found_nodes[mac2]
                    if prio > prev_prio:  # higher prio, discard the old one
                        self.links.pop(tuple(sorted((prev_mac1, mac2))), None)
                        found_nodes[mac2] = (mac1, prio)
                    else:  # lower prio, discard this one
                        self.links.pop((mac1, mac2), None)
                else:
                    found_nodes[mac2] = (mac1, prio)
                continue
        # The following will clear any remaining conflicts and ensure we
        # have no loops.
        # 1)  we initialize a set of 'accepted' connected groups of nodes,
        #     using the links that were detected during last
        #     scan, and record the set of unconfirmed links.
        # 2a) we drop unconfirmed links between 2 nodes already in the
        #     same connectivity group (otherwise it would create a loop).
        # 2b) we accept links between 2 nodes in different connectivity
        #     groups, and merge such a pair of connectivity groups into one.
        # 3)  we accept links between an accepted node (belonging
        #     to an accepted connectivity group) and a node not yet accepted.
        #     This newly accepted node is inserted into the connectivity group.
        # 4)  As soon as the set of connectivity groups evolves (i.e. 2b or 3)
        #     we loop again from step 2.
        # --
        # this is step 1
        while True:
            try:
                accepted_groups = Grouper()
                remaining_links = set()
                for mac1, mac2, port1, port2, confirmed, last_seen in self:
                    if confirmed:
                        try:
                            accepted_groups.group_items(mac1, mac2)
                        except AlreadyGroupedException:
                            # We tried to group mac1 & mac2 but they are already
                            # in the same group, so this means there is a loop
                            # of confirmed links. This can occur after the network
                            # was physically changed and the user just did a partial
                            # rescan of the network, for instance
                            # `walt device rescan <single-switch>`. In this case
                            # new data is combined with database data of other parts
                            # of the network which may be obsolete.
                            # let's save some data to analyse this loop later.
                            # (note: using mac2 instead of mac1 on the two following
                            # lines would be correct too.)
                            loop_candidate_macs = accepted_groups.get_friends(mac1)
                            mac_in_loop = mac1
                            raise  # leave the loop and process the exception below
                    else:
                        remaining_links.add((mac1, mac2))
                break  # done, break the while True loop
            except AlreadyGroupedException:
                # there is a loop somewhere between <loop_candidate_macs> and
                # we know <mac_in_loop> belongs to this loop.
                # a. gather the confirmed links between the candidate macs
                # b. analyse those links to find those forming a loop
                # c. remove the link with oldest last_seen attribute
                # -- step a
                candidate_links = []
                for mac1, mac2, port1, port2, confirmed, last_seen in self:
                    if confirmed and len(set((mac1, mac2)) & loop_candidate_macs) == 2:
                        candidate_links.append((mac1, mac2))
                # -- step b
                solver = LoopsSolver()
                loop_macs = solver.solve(mac_in_loop, candidate_links)
                loop_links = zip(loop_macs[:-1], loop_macs[1:])
                loop_links = tuple(tuple(sorted(t)) for t in loop_links)
                # -- step c
                oldest_last_seen, oldest_link = None, None
                for link in loop_links:
                    last_seen = self.links[link][3]
                    if oldest_last_seen is None or last_seen < oldest_last_seen:
                        oldest_last_seen, oldest_link = last_seen, link
                self.links.pop(oldest_link)
                continue  # retry step 1
        while True:
            # this is step 2
            still_moving = False
            for mac1, mac2 in remaining_links.copy():
                if mac1 in accepted_groups and mac2 in accepted_groups:
                    # we will process this link
                    remaining_links.remove((mac1, mac2))
                    if accepted_groups.is_same_group(mac1, mac2):
                        self.links.pop((mac1, mac2))  # 2a: discard
                    else:
                        accepted_groups.group_items(mac1, mac2)  # 2b: accept
                        still_moving = True
                        break
            if still_moving:
                continue
            # this is step 3
            still_moving = False
            for mac1, mac2 in remaining_links.copy():
                # since we passed step 2, the following condition is
                # implicitely an exclusive or
                if mac1 in accepted_groups or mac2 in accepted_groups:
                    # we will process this link
                    remaining_links.remove((mac1, mac2))
                    accepted_groups.group_items(mac1, mac2)  # accept
                    still_moving = True
                    break
            if still_moving:
                continue
            break

    def get_neighbors_mac(self, mac):
        for mac1, mac2 in self.links:
            if mac1 == mac:
                yield mac2
            if mac2 == mac:
                yield mac1

    def printed_tree(
        self,
        last_scan,
        stdout_encoding,
        root_mac,
        device_labels,
        device_types,
        lldp_forbidden,
        port_names,
        show_all,
    ):
        t = Tree(stdout_encoding)
        # compute confirmed / unconfirmed nodes
        confirmed_macs = set()
        all_macs = set()
        for mac1, mac2, port1, port2, confirmed, last_seen in self:
            all_macs.add(mac1)
            all_macs.add(mac2)
            if confirmed:
                confirmed_macs.add(mac1)
                confirmed_macs.add(mac2)
        # declare nodes
        for mac in all_macs:
            label = device_labels[mac]
            if device_types[mac] == "switch":
                label = "-- %s --" % label
            elif device_types[mac] == "unknown":
                label = "<? %s ?>" % label
            if mac not in confirmed_macs:
                label = "(%s)" % label
            t.add_node(mac, label)
        # declare children
        for mac1, mac2, port1, port2, confirmed, last_seen in self:
            for node_mac, parent_mac, parent_port in (
                (mac1, mac2, port2),
                (mac2, mac1, port1),
            ):
                if device_types[parent_mac] == "switch":
                    if show_all or device_types[node_mac] != "unknown":
                        parent_port = port_names.get(
                                (parent_mac, parent_port), parent_port)
                        t.add_child(parent_mac, parent_port, node_mac)
        # prune parts of the tree
        self.prune(t, root_mac, device_types, lldp_forbidden, show_all)
        # print tree and associated messages
        if last_scan is None:
            note_last_scan = NOTE_LAST_NETWORK_SCAN_UNKNOWN
        else:
            delay = time.time() - last_scan
            note_last_scan = NOTE_LAST_NETWORK_SCAN % human_readable_delay(delay)
        tips = TIPS_MIN
        notes = (note_last_scan,)
        if len(all_macs - confirmed_macs) > 0:
            notes = notes + (NOTE_EXPLAIN_UNREACHABLE,)
        if show_all:
            tips = (TIP_DEVICE_ADMIN_1,) + tips
            notes = notes + (NOTE_EXPLAIN_UNKNOWN,)
        else:
            tips = (TIP_ADD_FLAG_ALL,) + tips
        footer = (
            format_explanation("note", notes) + "\n" + format_explanation("tip", tips)
        )
        return "\n%s\n%s" % (t.printed(root=root_mac), footer)

    def prune(self, t, root_mac, device_types, lldp_forbidden, show_all):
        if not show_all:
            # prune parts of the tree with no node
            seen = set()

            def node_count_prune(mac):
                seen.add(mac)
                if device_types[mac] == "node":
                    count = 1
                else:
                    count = sum(
                        node_count_prune(child_mac)
                        for child_mac in t.children(mac)
                        if child_mac not in seen
                    )
                # In some cases, lldp & bridge table retrieval may be forbidden
                # on a switch but we may still display the tree appropriately thanks
                # to information coming from neighboring devices.
                # In this case, even if queries are forbidden on this specific switch,
                # we still want to display the subtree rooted there.
                # All in all, we prune the subtree only if no nodes are found there.
                if device_types[mac] == "switch" and count == 0:
                    if mac in lldp_forbidden:
                        # No nodes there, but let's indicate it is probably because
                        # exploration is forbidden.
                        t.prune(mac, "[...] ~> forbidden (cf. walt device config)")
                    else:
                        t.prune(mac, "[...] ~> no nodes there")
                return count

            node_count_prune(root_mac)


class TopologyManager(object):
    def __init__(self):
        self.last_scan = None

    def print_message(self, requester, message):
        if requester is not None:
            requester.stdout.write(message + "\n")
            requester.stdout.flush()
        print(message)

    def collect_devices(self, requester, server, devices):
        vpnnodes = server.db.select("vpnnodes")
        vpnmac_to_mac = dict(vpnnodes[["vpnmac", "mac"]])
        lldp_topology = LinkLayerTopology(vpnmac_to_mac)
        bridge_topology = BridgeTopology(vpnmac_to_mac)
        server_mac = server.devices.get_server_mac()
        server_ip = get_server_ip()
        for device in devices:
            if device.type == "server":
                self.collect_connected_devices(
                    requester,
                    server,
                    server_mac,
                    server_ip,
                    lldp_topology,
                    None,
                    "walt server",
                    server_ip,
                    device.mac,
                    const.SERVER_SNMP_CONF,
                )
            elif device.type == "switch":
                if not device.conf.get("lldp.explore", False):
                    self.print_message(
                        requester,
                        "Querying %-25s FORBIDDEN (see: walt help show device-config)"
                        % device.name,
                    )
                    continue
                snmp_conf = {
                    "version": device.conf.get("snmp.version"),
                    "community": device.conf.get("snmp.community"),
                }
                self.collect_connected_devices(
                    requester,
                    server,
                    server_mac,
                    server_ip,
                    lldp_topology,
                    bridge_topology,
                    device.name,
                    device.ip,
                    device.mac,
                    snmp_conf,
                )
            else:
                self.print_message(
                    requester,
                    "Querying %-25s INVALID (can only scan switches or the server)"
                    % device.name,
                )
        return lldp_topology, bridge_topology

    def collect_connected_devices(
        self,
        requester,
        server,
        server_mac,
        server_ip,
        lldp_topology,
        bridge_topology,
        host_name,
        host_ip,
        host_mac,
        host_snmp_conf,
    ):
        print("Querying %s..." % host_name)
        if host_ip is None:
            self.print_message(
                requester, "Querying %-25s FAILED (unknown management IP!)" % host_name
            )
            return
        lldp_error = self.get_and_process_lldp_neighbors(
            server,
            server_mac,
            server_ip,
            lldp_topology,
            host_name,
            host_ip,
            host_mac,
            host_snmp_conf,
        )
        if bridge_topology is None:
            message = {
                None: "OK",
                "snmp-variant": "FAILED (LLDP SNMP issue)",
                "snmp-issue": "FAILED (LLDP SNMP issue)",
            }[lldp_error]
        else:
            bridge_error = self.get_and_process_bridge_neighbors(
                server,
                server_mac,
                server_ip,
                bridge_topology,
                host_name,
                host_ip,
                host_mac,
                host_snmp_conf,
            )
            message = {
                (None, None): "OK",
                (None, "snmp-variant"): "OK (LLDP-only data)",
                (None, "snmp-issue"): "OK (LLDP-only data)",
                ("snmp-variant", None): "OK (BRIDGE-only data)",
                (
                    "snmp-variant",
                    "snmp-variant",
                ): "FAILED (LLDP and BRIDGE SNMP issues)",
                ("snmp-variant", "snmp-issue"): "FAILED (LLDP and BRIDGE SNMP issues)",
                ("snmp-issue", None): "OK (BRIDGE-only data)",
                ("snmp-issue", "snmp-variant"): "FAILED (LLDP and BRIDGE SNMP issues)",
                ("snmp-issue", "snmp-issue"): "FAILED (LLDP and BRIDGE SNMP issues)",
            }[(lldp_error, bridge_error)]
        self.print_message(requester, ("Querying %-25s " % host_name) + message)

    def get_and_process_lldp_neighbors(
        self,
        server,
        server_mac,
        server_ip,
        topology,
        host_name,
        host_ip,
        host_mac,
        host_snmp_conf,
    ):
        try:
            snmp_proxy = snmp.Proxy(host_ip, host_snmp_conf, lldp=True)
        except NoSNMPVariantFound:
            return "snmp-variant"
        try:
            neighbors = snmp_proxy.lldp.get_neighbors().items()
        except SNMPException:
            return "snmp-issue"
        for port, neighbor_info in neighbors:
            ip, mac, sysname = (
                neighbor_info["ip"],
                neighbor_info["mac"],
                neighbor_info["sysname"],
            )
            print(
                "---- lldp: found on %s %s -- port %d: %s %s %s"
                % (host_name, host_mac, port, ip, mac, sysname)
            )
            # The switch connected to the server detects the mac address of the physical
            # network interface, which is different from the mac address of walt-net
            # (the one we use to identify the server in our database).
            # However walt-server-lldpd is setup to properly announce the IP address of
            # walt-net as its management address.
            # Thus if ip is server ip, we update mac address to the one of walt-net.
            if ip == server_ip:
                mac = server_mac
            topology.register_neighbor(host_mac, port, mac)
            info = dict(mac=mac, ip=ip, name=sysname.lower())
            db_info = server.devices.get_device_info(mac=mac)
            if db_info is None:
                # new device, call add_or_update_device to add it
                server.add_or_update_device(**info)
            elif ip != db_info.ip:
                # call add_or_update_device to update ip
                info.update(mac=db_info.mac,
                            type=db_info.type,
                            name=db_info.name)
                server.add_or_update_device(**info)
        return None  # no error

    def get_and_process_bridge_neighbors(
        self,
        server,
        server_mac,
        server_ip,
        topology,
        host_name,
        host_ip,
        host_mac,
        host_snmp_conf,
    ):
        # SNMP communication
        try:
            snmp_proxy = snmp.Proxy(host_ip, host_snmp_conf, bridge=True)
        except NoSNMPVariantFound:
            return "snmp-variant"
        try:
            macs_per_port = snmp_proxy.bridge.get_macs_per_port()
            secondary_macs = snmp_proxy.bridge.get_secondary_macs()
        except SNMPException:
            return "snmp-issue"
        # Register secondary switch macs
        topology.register_secondary_macs(host_mac, secondary_macs)
        # Register switch neighbors --
        # This is the switch forwarding table, so mac addresses may not be
        # immediate neighbors.
        # We don't get neighbor IPs here (unlike LLDP), so we cannot register new
        # devices in db.
        for port, macs in macs_per_port.items():
            msg = ", ".join(macs)
            print(f"---- bridge: found on {host_name} {host_mac} -- port {port}: {msg}")
            for mac in macs:
                topology.register_neighbor(host_mac, port, mac)
        return None  # no error

    def rescan(self, requester, server, db, devices):
        # note: the last parameter of this method is called "devices" and
        # not "switches" because the server may also be included in this
        # list of devices to be probed.

        # update self.last_scan
        self.last_scan = time.time()

        # explore the network equipments
        lldp_topology, bridge_topology = self.collect_devices(
            requester, server, devices
        )

        # help bridge data analysis by adding lldp confirmed data to bridge topology
        bridge_topology.add_ll_confirmed_data(lldp_topology)

        # deduce link-layer topology from bridge data
        ll_br_topology = bridge_topology.deduce_link_layer_topology(db)

        # merge with priority to LLDP data
        ll_br_topology.set_confirm_all(False)
        new_topology = lldp_topology
        new_topology.merge_other(ll_br_topology)
        new_topology.set_confirm_all(True)

        # retrieve past topology data from db
        db_topology = LinkLayerTopology({})
        db_topology.load_from_db(db)
        db_topology.unconfirm(devices)

        # merge with db data
        # (last_seen attribute will give priority to new data)
        new_topology.merge_other(db_topology)

        # cleanup conflicting data (obsolete vs confirmed)
        nodes_mac = set(n.mac for n in db.select("nodes"))
        new_topology.cleanup(nodes_mac)

        # commit to db
        new_topology.save_to_db(db)
        return new_topology

    def get_sw_port_name(self, db, sw_mac, sw_port):
        port_info = db.select_unique("switchports", mac=sw_mac, port=sw_port)
        if port_info is None:
            return f"{sw_port}"
        if port_info.name is None:
            return f"{sw_port}"
        return port_info.name

    def report_lldp_neighbor(self, server, db,
             sw_mac, sw_name, sw_ip,
             sw_port_lldp_label, node_mac, node_name):
        # check if we know which port number corresponds to the label
        sw_port = get_port_number_from_lldp_label(sw_ip, sw_port_lldp_label)
        if sw_port is None:
            # no, so:
            # 1. rescan the switch (this will update the topology in db)
            # 2. look for the neighbor having mac=node_mac
            # 3. record that sw_port_lldp_label corresponds to this port
            sw_info = db.select_unique("devices", mac=sw_mac)
            topology = self.rescan(None, server, db, (sw_info,))
            sw_mac_again, sw_port, confirmed = topology.locate_mac(node_mac)
            if (None in (sw_mac_again, sw_port, confirmed) or
                confirmed is False or
                sw_mac != sw_mac_again):
                # for some reason (communication failure?) node_mac was
                # not detected by the scan, we cannot continue
                return
            # all fine, record the lldp label for next time
            save_lldp_label_for_port_number(sw_ip, sw_port, sw_port_lldp_label)
            updated = True
        else:
            updated = db.update_node_location(node_mac, sw_mac, sw_port)
        if updated:
            sw_port_name = self.get_sw_port_name(db, sw_mac, sw_port)
            logline = (f"Node {node_name} is now connected "
                       f"on {sw_name} port {sw_port_name}")
            server.logs.platform_log("devices", line=logline)

    def get_tree_root_mac(self, server, db_topology):
        # the root of the tree should be the main switch.
        # we analyse the neighbors of this server:
        # - if we find one, we return it
        # - if we find several ones, we favor the ones in
        #   walt-net or walt-adm (thus we discard neighbors found from walt-out)
        # - if we still find several ones, we favor the ones which type is known
        #   as a switch
        server_mac = server.devices.get_server_mac()
        unknown_neighbors = []
        for neighbor_mac in db_topology.get_neighbors_mac(server_mac):
            info = server.devices.get_device_info(mac=neighbor_mac)
            if info.ip is None:
                continue  # ignore this device
            if not (ip_in_walt_network(info.ip) or ip_in_walt_adm_network(info.ip)):
                continue  # ignore this device
            if info.type == "unknown":
                unknown_neighbors.append(info.name)
                continue  # possibly the switch we are looking for
            if info.type == "switch":
                return (True, neighbor_mac)  # Found it!
        # if we are here we did not find what we want
        out = MSG_UNKNOWN_TOPOLOGY
        if len(unknown_neighbors) > 0:
            out += format_sentence(
                "Note: %s was(were) detected, but its(their) type is unknown.\n"
                + "If it(one of them) is a switch, use:\n"
                + "$ walt device config <device> type=switch\n",
                unknown_neighbors,
                None,
                "device",
                "devices",
            )
        return (False, out)

    def tree(self, requester, server, db, show_all):
        db_topology = LinkLayerTopology({})
        db_topology.load_from_db(db)
        if db_topology.is_empty():
            return MSG_UNKNOWN_TOPOLOGY
        tree_root_info = self.get_tree_root_mac(server, db_topology)
        if tree_root_info[0] is False:  # failed
            return tree_root_info[1]  # return error message
        root_mac = tree_root_info[1]
        # compute device mac to label and type associations
        device_labels = {d.mac: d.name for d in db.select("devices")}
        device_types = {d.mac: d.type for d in db.select("devices")}
        lldp_forbidden = set(
            d.mac
            for d in db.select("devices", type="switch")
            if d.conf.get("lldp.explore", False) is False
        )
        # get optional switch port names
        port_names = {(sp.mac, sp.port): sp.name for sp in db.select("switchports")}
        # compute and return the topology tree
        stdout_encoding = requester.stdout.get_encoding()
        return db_topology.printed_tree(
            self.last_scan,
            stdout_encoding,
            root_mac,
            device_labels,
            device_types,
            lldp_forbidden,
            port_names,
            show_all,
        )
