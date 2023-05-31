import random
import sys
import time
from collections import defaultdict
from copy import deepcopy
from ipaddress import IPv4Network
from pathlib import Path
from textwrap import wrap

import netifaces
from plumbum.cli.terminal import prompt
from walt.client.doc.md import display_doc
from walt.common.formatting import columnate, format_sentence, framed, highlight
from walt.common.term import alternate_screen_buffer, choose, clear_screen

EDITOR_TOP_MESSAGE = """\
Please review and validate or edit the proposed network configuration.
"""
MENU_NAVIGATION_TIP = "use arrow keys to browse, <enter> to select"

MESSAGE_NO_INTERFACE = framed(
    "Note",
    "\n".join(wrap("""\
No usable wired interface was detected on this machine, so the server will be \
configured for virtual-only mode. \
This means only virtual nodes can be registered on this WALT server for now. \
If in the future a new network adapter is plugged in (or a missing network \
driver is installed), just restart `walt-server-setup --edit-conf` to update \
the platform configuration.""")),
)

MESSAGE_VIRTUAL_ONLY = framed(
    "Note",
    "\n".join(wrap("""\
The selected configuration corresponds to a virtual-only mode (i.e. walt-net \
is not linked to a physical network interface). \
This means only virtual nodes can be registered on this WALT server for now. \
If needed, you can restart `walt-server-setup --edit-conf` later to update \
this platform configuration.""")),
)

# tools
# -----


def get_net_desc(netname):
    return {"walt-net": "platform network", "walt-adm": "switches admin network"}.get(
        netname, "unmanaged network"
    )


def get_virtual_only_netconf():
    # return virtual-only platform
    random_ip_conf = f"192.168.{random.randint(0, 253)}.1/24"
    return {"walt-net": {"raw-device": None, "ip": random_ip_conf}}


def is_virtual_only_netconf(netconf):
    return netconf["walt-net"].get("raw-device", None) is None


def validate_ipv4_network(x):
    net = IPv4Network(x, strict=False)
    if net.prefixlen == 32:
        raise ValueError(
            "The full network should be specified, not the single IP address."
        )
    return x


def get_default_gateway_interfaces():
    return set(gw_info[1] for gw_info in netifaces.gateways()["default"].values())


def iter_wired_physical_interfaces():
    for intf_dev_dir in Path("/sys/class/net").glob("*/device"):
        intf_dir = intf_dev_dir.parent
        if (intf_dir / "wireless").exists():
            continue
        yield intf_dir.name


def get_mac_address(intf):
    return Path(f"/sys/class/net/{intf}/address").read_text().strip()


def sanitize_netconf(netconf):
    if netconf is None:
        return
    for netnameconf in netconf.values():
        if "raw-device" not in netnameconf:
            netnameconf["raw-device"] = None
        if netnameconf["raw-device"] is None:
            netnameconf.pop("vlan", None)


def wait_message_read():
    print(" " * 71 + "]\r[", end="")
    sys.stdout.flush()
    for i in range(70):
        print("*", end="")
        sys.stdout.flush()
        time.sleep(0.28)
    print("\r" + " " * 72 + "\r", end="")
    sys.stdout.flush()


# pretty printing netconf
# -----------------------


def netname_row_values(netconf, netname):
    net_desc = get_net_desc(netname)
    netnameconf = netconf[netname]
    phys_intf = netnameconf.get("raw-device", None)
    if phys_intf is None and netname != "walt-net":
        phys_intf = highlight("undefined")
        vlan = None
        ipconf_type = None
        ipconf = None
    else:
        if phys_intf is None:  # implicitly this is walt-net
            phys_intf = "none (virtual-only platform)"
            vlan = None
        else:
            vlan = netnameconf.get("vlan", "No")
        if "ip" not in netnameconf:
            ipconf_type = highlight("undefined")
            ipconf = None
        elif netnameconf["ip"] == "dhcp":
            ipconf_type = "dhcp"
            ipconf = "auto"
        else:
            ipconf_type = "static"
            ipconf = netnameconf["ip"]
    return (highlight(netname), net_desc, phys_intf, vlan, ipconf_type, ipconf)


def pretty_print_netconf(netconf):
    ordering = {netname: index for index, netname in enumerate(netconf.keys())}
    # ensure walt-net and walt-adm are listed first
    ordering["walt-net"] = -2
    if "walt-adm" in ordering:
        ordering["walt-adm"] = -1
    netnames = sorted(ordering.keys(), key=lambda netname: ordering[netname])
    header = [
        "network",
        "description",
        "phys. intf.",
        "vlan tagging",
        "ip mode",
        "ip conf",
    ]
    rows = []
    for netname in netnames:
        rows.append(netname_row_values(netconf, netname))
    print(
        framed(
            "WalT network configuration",
            columnate(rows, header, shrink_empty_cols=True),
        )
    )


def print_netconf_status(context, netconf):
    s = "Configuration status: "
    undefined = []
    for netname, netnameconf in netconf.items():
        if "raw-device" not in netnameconf:
            undefined.append("physical interface for " + netname)
        elif "ip" not in netnameconf:
            undefined.append("IP conf of " + netname)
    if len(undefined) > 0:
        print(
            s + highlight("incomplete") + " (tip: define " + ", ".join(undefined) + ")"
        )
        return False  # incomplete
    info_per_vlan_intf = defaultdict(lambda: defaultdict(set))
    info_per_plain_intf = defaultdict(set)
    gw_conflicts = []
    for netname, netnameconf in netconf.items():
        if "raw-device" in netnameconf:
            phys_intf = netnameconf["raw-device"]
            vlan = netnameconf.get("vlan", None)
            if vlan is None:
                info_per_plain_intf[phys_intf].add(netname)
            else:
                info_per_vlan_intf[phys_intf][vlan].add(netname)
                vlan_intf = f"{phys_intf}.{vlan}"
                # check that selected interface is not a gateway
                # note: if a plain interface was used as a gateway, it was
                # already removed from the list "wired_interfaces", but
                # here we check about vlan interfaces.
                if vlan_intf in context["gw_interfaces"]:
                    gw_conflicts.append((phys_intf, vlan))
    if len(gw_conflicts) > 0:
        # for conciseness we just notify the first conflict.
        phys_intf, vlan = gw_conflicts[0]
        explain = (
            f"VLAN {vlan} on interface {phys_intf} seems to be used by your OS default"
            " gateway."
        )
        print(s + highlight("invalid") + "\n" + explain)
        return False  # invalid
    intf_conflicts = []
    # netnames using the same plain interface
    for phys_intf, netnames in info_per_plain_intf.items():
        if len(netnames) > 1:
            intf_conflicts.append((phys_intf, netnames))
    # netnames using the same VLAN on the same interface
    for phys_intf, info in info_per_vlan_intf.items():
        for vlan, netnames in info.items():
            if len(netnames) > 1:
                intf_conflicts.append((phys_intf, netnames))
    # netnames using the same interface for plain and VLAN configs
    for phys_intf, info in info_per_vlan_intf.items():
        if phys_intf in info_per_plain_intf:
            all_netnames = set(info_per_plain_intf[phys_intf])
            for vlan, netnames in info.items():
                all_netnames |= netnames
            intf_conflicts.append((phys_intf, all_netnames))
    if len(intf_conflicts) > 0:
        # for conciseness we just notify the first conflict.
        phys_intf, netnames = intf_conflicts[0]
        explain = format_sentence(
            (
                f"%s cannot use the same interface {phys_intf} unless they use"
                " different VLANs."
            ),
            netnames,
            None,
            None,
            "Networks",
        )
        print(s + highlight("invalid") + "\n" + explain)
        return False  # invalid
    print(s + "OK")
    return True  # valid


# main menu
# ---------


def select_main_menu(context, netconf):
    context["menu_info_function"] = main_menu_info


def main_menu_info(context, netconf, valid):
    options = {}
    for netname, netnameconf in netconf.items():
        # we only handle modifications of walt-net and walt-adm in this script
        if netname not in ("walt-adm", "walt-net"):
            continue
        options.update(
            {f"edit {netname} configuration": (select_interface_edit_menu, netname)}
        )
    if "walt-adm" not in netconf and not is_virtual_only_netconf(netconf):
        options.update({"define the optional walt-adm network": (define_walt_adm,)})
    options.update({"display help page about WalT networking": (show_networking_doc,)})
    if not same_netconfs(context["initial_netconf"], netconf):
        options.update({"discard changes": (discard_changes,)})
    if valid:
        options["validate and quit"] = (exit_conf,)
    return f"Main menu ({MENU_NAVIGATION_TIP}):", options


def define_walt_adm(context, netconf):
    netconf["walt-adm"] = {}
    select_interface_edit_menu(context, netconf, "walt-adm")


def show_networking_doc(context, netconf):
    display_doc("networking")


def discard_changes(context, netconf):
    netconf.clear()
    netconf.update(context["initial_netconf"])


def exit_conf(context, netconf):
    context.update(should_continue=False)


# interface edit menu
# -------------------


def select_interface_edit_menu(context, netconf, netname):
    context["menu_info_function"] = (
        lambda context, netconf, valid: edit_interface_menu_info(
            context, netconf, netname
        )
    )


def edit_interface_menu_info(context, netconf, netname):
    options = {}
    netnameconf = netconf[netname]
    has_phys_interface = netnameconf.get("raw-device", None) is not None
    verb = "change" if has_phys_interface else "define"
    options.update(
        {
            f"{netname} -- {verb} the physical interface": (
                define_physical_interface,
                netname,
            )
        }
    )
    if has_phys_interface:
        if "vlan" in netnameconf:
            options.update(
                {f"{netname} -- disable VLAN tagging": (disable_vlan, netname)}
            )
            options.update({f"{netname} -- change VLAN tag": (change_vlan, netname)})
        else:
            options.update(
                {f"{netname} -- enable VLAN tagging": (change_vlan, netname)}
            )
    if netname == "walt-net" or has_phys_interface:
        verb = "change" if "ip" in netnameconf else "define"
        options.update({f"{netname} -- edit IP configuration": (edit_ip, netname)})
    if netname == "walt-adm":
        options.update(
            {f"{netname} -- disable this optional network": (disable_walt_adm,)}
        )
    options.update({"Return to main menu": (select_main_menu,)})
    return f"{netname} configuration menu ({MENU_NAVIGATION_TIP}):", options


def define_physical_interface(context, netconf, netname):
    choices = {
        f"{intf} -- mac address {get_mac_address(intf)}": intf
        for intf in context["wired_interfaces"]
    }
    if netname == "walt-net" and "walt-adm" not in netconf:
        choices["None -- virtual-only platform, start with this if unsure"] = None
    intf = choose(
        f"Please select on which interface {netname} should be connected:", choices
    )
    netconf[netname]["raw-device"] = intf


def disable_vlan(context, netconf, netname):
    del netconf[netname]["vlan"]


def change_vlan(context, netconf, netname):
    number = prompt("VLAN number:", type=int, validator=lambda x: x >= 0)
    netconf[netname]["vlan"] = number


def edit_ip(context, netconf, netname):
    if netname == "walt-net":
        print(
            "The walt server fully manages this walt-net network and provides its own"
            " DHCP server."
        )
        print()
        print("The only change allowed here is the IP network subnet.")
        print(
            "It may be useful to define a larger one if the platform has to grow with"
            " many devices."
        )
        print()
        ip_mode = "static"
    else:
        ip_mode = choose("Select IP configuration mode:", ["dhcp", "static"])
    if ip_mode == "dhcp":
        ip_conf = "dhcp"
    else:  # static
        try:
            ip_conf = prompt(
                "Please enter IP configuration (e.g. 10.0.12.55/27):",
                type=str,
                validator=validate_ipv4_network,
            )
        except KeyboardInterrupt:
            return
    netconf[netname]["ip"] = ip_conf


def disable_walt_adm(context, netconf):
    del netconf["walt-adm"]
    select_main_menu(context, netconf)


# main module entrypoints
# -----------------------


def get_default_netconf():
    return get_virtual_only_netconf()


def edit_netconf_interactive(netconf):
    # netconf probably comes from walt.server.conf['network'], ensure we will not
    # modify this configuration directly by performing a deep copy of the object
    netconf = deepcopy(netconf)
    print("Detecting wired network interfaces... ", end="")
    sys.stdout.flush()
    wired_interfaces = []
    notes = []
    gw_interfaces = get_default_gateway_interfaces()
    for intf in iter_wired_physical_interfaces():
        if intf in gw_interfaces:
            notes.append(f"note: ignored {intf}, already in use as a default gateway.")
        else:
            wired_interfaces.append(intf)
    print("done")
    if len(notes) > 0:
        print("\n".join(notes))
    if len(wired_interfaces) == 0:
        print(MESSAGE_NO_INTERFACE)
        wait_message_read()
        return get_virtual_only_netconf()
    # ready for the interactive screen
    print("Entering network configuration editor... ", end="")
    sys.stdout.flush()
    time.sleep(2)
    if netconf is None:
        netconf = get_default_netconf()
    context = dict(
        initial_netconf=deepcopy(netconf),
        wired_interfaces=wired_interfaces,
        gw_interfaces=gw_interfaces,
        should_continue=True,
        return_value=None,
        menu_info_function=main_menu_info,
    )
    with alternate_screen_buffer():
        while True:
            clear_screen()
            print()
            print(EDITOR_TOP_MESSAGE)
            pretty_print_netconf(netconf)
            valid = print_netconf_status(context, netconf)
            print()
            menu_info_function = context["menu_info_function"]
            menu_title, menu_options = menu_info_function(context, netconf, valid)
            selected = choose(menu_title, menu_options)
            action = selected[0]
            action_args = selected[1:]
            print()
            action(context, netconf, *action_args)
            if not context["should_continue"]:
                break
    print("done")
    sanitize_netconf(netconf)
    if is_virtual_only_netconf(netconf):
        print(MESSAGE_VIRTUAL_ONLY)
        wait_message_read()
    return netconf


def get_netconf_entry_comments(netconf):
    return {f"{netname}:": get_net_desc(netname) for netname in netconf}


def same_netconfs(nc1, nc2):
    sanitize_netconf(nc1)
    sanitize_netconf(nc2)
    return nc1 == nc2
