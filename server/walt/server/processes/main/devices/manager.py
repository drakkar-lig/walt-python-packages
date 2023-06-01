import re

from walt.common.formatting import columnate, format_paragraph
from walt.common.netsetup import NetSetup
from walt.common.tools import do, get_mac_address
from walt.server import const
from walt.server.tools import (
    get_server_ip,
    get_walt_subnet,
    ip_in_walt_network,
    merge_named_tuples,
    to_named_tuple,
)

DEVICE_NAME_NOT_FOUND = """No device with name '%s' found.\n"""

NEW_NAME_ERROR_AND_GUIDELINES = """\
Failed: invalid new name.
This name must be a valid network hostname.
Only alphanumeric characters and '-' are allowed.
The 1st character must be an alphabet letter.
The name must be at least 2-chars long.
(Example: rpi-D327)
"""

DEVICES_QUERY = """\
WITH infodev AS (SELECT name, ip, mac,
       CASE WHEN type = 'node' AND virtual THEN 'node (virtual)'
            WHEN type = 'node' AND mac like '52:54:00:%%' THEN 'node (vpn)'
            WHEN type = 'node' THEN 'node (physical)'
            ELSE type
       END as type,
COALESCE((conf->'netsetup')::int, 0) as int_netsetup
FROM devices)
SELECT name, ip, mac, type,
CASE WHEN int_netsetup = 0 THEN 'LAN'
     WHEN int_netsetup = 1 THEN 'NAT'
END as netsetup
FROM infodev
WHERE type %(unknown_op)s 'unknown'
ORDER BY type, name;"""

MY_NODES_QUERY = """\
SELECT  d.mac as mac
FROM devices d, nodes n
WHERE   d.mac = n.mac
AND     split_part(n.image, '/', 1) = '%s'
ORDER BY name;"""

DEVICE_SET_QUERIES = {
    "all-nodes": """
            SELECT  d.mac as mac
            FROM devices d, nodes n
            WHERE   d.mac = n.mac
            ORDER BY d.name;""",
    "free-nodes": """
            SELECT  d.mac as mac
            FROM devices d, nodes n
            WHERE   d.mac = n.mac
            AND     n.image = ('waltplatform/' || n.model || '-default:latest')
            ORDER BY name;""",
    "all-switches": """
            SELECT  d.mac as mac
            FROM devices d
            WHERE   d.type = 'switch'
            ORDER BY name;""",
    "all-devices": """
            SELECT  d.mac as mac
            FROM devices d
            ORDER BY type, name;""",
    "explorable-switches": """
            SELECT  d.mac as mac
            FROM devices d
            WHERE   d.type = 'switch'
            AND     COALESCE((d.conf->'lldp.explore')::boolean, False) = True
            ORDER BY d.name;""",
}

TITLE_DEVICE_SHOW_MAIN = """\
The WalT network contains the following devices:"""

FOOTNOTE_DEVICE_SHOW_MAIN = """\
tips:
- use 'walt device tree' for a tree view of the network
- use 'walt device forget <device_name>' to make WalT forget about an obsolete device"""

TITLE_SOME_UNKNOWN_DEVICES = """\
WalT also detected the following devices but could not detect their type:"""

FOOTNOTE_SOME_UNKNOWN_DEVICES = """\
If one of them is actually a switch,\
 use 'walt device config <name> type=switch' to fix this."""

CMD_ADD_SSH_KNOWN_HOST = (
    "  mkdir -p /root/.ssh && ssh-keygen -F %(ip)s ||                            "
    " ssh-keyscan -t ecdsa %(ip)s >> /root/.ssh/known_hosts"
)


class DevicesManager(object):
    def __init__(self, server):
        self.db = server.db
        self.logs = server.logs
        self.server_mac = get_mac_address(const.WALT_INTF)
        self.server_ip = get_server_ip()
        self.netmask = str(get_walt_subnet().netmask)

    def prepare(self):
        # prepare the network setup for NAT support
        self.prepare_netsetup()

    def cleanup(self):
        self.cleanup_netsetup()

    def get_server_mac(self):
        return self.server_mac

    def validate_device_name(self, requester, name):
        if self.get_device_info(requester, name, err_message=None) is not None:
            if requester is not None:
                requester.stderr.write(
                    """Failed: a device with name '%s' already exists.\n""" % name
                )
            return False
        if len(name) < 2 or not re.match("^[a-zA-Z][a-zA-Z0-9-]*$", name):
            if requester is not None:
                requester.stderr.write(NEW_NAME_ERROR_AND_GUIDELINES)
            return False
        return True

    def rename(self, requester, old_name, new_name):
        device_info = self.get_device_info(requester, old_name)
        if device_info is None:
            return False
        if not self.validate_device_name(requester, new_name):
            return False
        # all is fine, let's update it
        self.db.update("devices", "mac", mac=device_info.mac, name=new_name)
        self.db.commit()
        return True

    def get_type(self, mac):
        device_info = self.db.select_unique("devices", mac=mac)
        if not device_info:
            return None
        return device_info.type

    def get_device_info(
        self, requester, device_name, err_message=DEVICE_NAME_NOT_FOUND
    ):
        device_info = self.db.select_unique("devices", name=device_name)
        if device_info is None and err_message is not None and requester is not None:
            requester.stderr.write(err_message % device_name)
        return device_info

    def get_complete_device_info(self, mac):
        device_info = self.db.select_unique("devices", mac=mac)
        if device_info is None:
            return None
        device_type = device_info.type
        if device_type == "node":
            node_info = self.db.select_unique("nodes", mac=mac)
            # netsetup=NAT can actually be applied to all devices, not only
            # nodes. However, considering only nodes ensures these devices
            # will really boot in walt-net and the netmask + gateway pair
            # will be correct. So we only expose this information to nodes.
            if device_info.conf.get("netsetup", 0) == NetSetup.NAT:
                gateway = self.server_ip
            else:
                gateway = ""
            node_info = to_named_tuple(node_info._asdict())
            node_info = node_info.update(gateway=gateway, netmask=self.netmask)
            device_info = merge_named_tuples(device_info, node_info)
        elif device_type == "switch":
            switch_info = self.db.select_unique("switches", mac=mac)
            device_info = merge_named_tuples(device_info, switch_info)
        return device_info

    def get_name_from_ip(self, ip):
        device_info = self.db.select_unique("devices", ip=ip)
        if device_info is None:
            return None
        return device_info.name

    def notify_unknown_ip(self, requester, device_name):
        requester.stderr.write("Sorry, IP address of %s in unknown.\n" % device_name)

    def get_device_ip(self, requester, device_name):
        device_info = self.get_device_info(requester, device_name)
        if device_info is None:
            return None  # error already reported
        if device_info.ip is None:
            self.notify_unknown_ip(requester, device_name)
        return device_info.ip

    def generate_device_name(self, type, mac, **kwargs):
        if type == "server":
            return "walt-server"
        else:
            prefix = "%s-%s" % (type, "".join(mac.split(":")[3:]))
            i = 1
            while True:
                if i == 1:
                    name = prefix
                else:
                    name = "%s-%d" % (prefix, i)
                device_info = self.db.select_unique("devices", name=name)
                if device_info is None:
                    # ok name does not exist in db yet
                    return name
                else:
                    # device name already exists! Check next one.
                    i += 1

    def add_or_update(self, requester=None, **args_data):
        """Returns whether a new equipment (node, switch) was identified"""
        if "type" not in args_data:
            args_data["type"] = "unknown"
        new_equipment = False
        modified = False
        newly_identified = False
        db_data = self.db.select_unique("devices", mac=args_data["mac"])
        if db_data:
            # -- device found in db
            updates = {}
            name = db_data.name
            if db_data.type == "unknown" and args_data["type"] != "unknown":
                # device was in db, but type was unknown.
                if "unknown" in db_data.name:
                    # device name has not been updated by the user,
                    # we will generate a new one more appropriate for the new type
                    name = self.generate_device_name(**args_data)
                    updates["name"] = name
                    self.logs.platform_log(
                        "devices", f"renamed {db_data.name} to {name} for clarity"
                    )
                    if requester is not None:
                        requester.stdout.write(
                            f"Renaming {db_data.name} to {name} for clarity.\n"
                        )
                # now we know its type, so we consider we have a new equipment here.
                new_equipment = True
                newly_identified = True
                print(
                    "Device: %s updating type, unknown -> %s"
                    % (name, args_data["type"])
                )
                updates["type"] = args_data["type"]
            if db_data.ip is None and args_data.get("ip", None) is not None:
                print("Device: %s updating ip, unknown -> %s" % (name, args_data["ip"]))
                updates["ip"] = args_data["ip"]
            elif (
                db_data.ip is not None
                and args_data.get("ip", None) is not None
                and not ip_in_walt_network(db_data.ip)
                and ip_in_walt_network(args_data["ip"])
            ):
                # the device updated its IP by requesting our managed DHCP server
                print(
                    "Device: %s updating ip, %s -> %s (now in walt network)"
                    % (name, db_data.ip, args_data["ip"])
                )
                updates["ip"] = args_data["ip"]
            if len(updates) > 0:
                modified = True
                self.db.update("devices", "mac", mac=args_data["mac"], **updates)
        else:
            # device was not known in db yet
            # generate a name for this device
            if "name" not in args_data:
                args_data["name"] = self.generate_device_name(**args_data)
            print(
                "Device: %s is new, adding (%s, %s)"
                % (args_data["name"], args_data["ip"], args_data["type"])
            )
            self.db.insert("devices", **args_data)
            modified = True
            new_equipment = True
        # if new switch or node, insert in relevant table
        # and submit platform logline
        # but first, refresh after prev updates
        db_data = self.db.select_unique("devices", mac=args_data["mac"])
        if new_equipment:
            if newly_identified:
                ident_log_line = " (device type previously unknown)"
            else:
                ident_log_line = ""
            if db_data.type == "switch":
                self.db.insert("switches", **args_data)
                dtype = "switch"
                details = ""
            elif db_data.type == "node":
                self.db.insert("nodes", **args_data)
                dtype = "node"
                details = f" model={args_data['model']}"
            else:
                dtype = "device"
                details = f" type={db_data.type}"
            info = f"name={db_data.name}{details} mac={db_data.mac} ip={db_data.ip}"
            logline = f"new {dtype}{ident_log_line} {info}"
            self.logs.platform_log("devices", logline)
        else:  # otherwise update them
            if db_data.type == "switch":
                self.db.update("switches", "mac", **args_data)
            elif db_data.type == "node":
                self.db.update("nodes", "mac", **args_data)
        if modified:
            self.db.commit()
        return new_equipment

    def show_device_table(self, unknown_or_not):
        unknown_op = "=" if unknown_or_not else "!="
        q = DEVICES_QUERY % dict(unknown_op=unknown_op)
        rows, header = self.db.pretty_print_select_info(q)
        # Do no print the netsetup status for the server
        # or devices outside walt-net
        idx_type = header.index("type")
        idx_ip = header.index("ip")
        idx_netsetup = header.index("netsetup")
        fixed_rows = []
        for row in rows:
            if (
                row[idx_type] == "server"
                or row[idx_ip] is None
                or not ip_in_walt_network(row[idx_ip])
            ):
                row = list(row)  # for assignment, it was a tuple
                row[idx_netsetup] = ""
            fixed_rows.append(row)
        return columnate(fixed_rows, header)

    def show(self):
        msg = format_paragraph(
            TITLE_DEVICE_SHOW_MAIN,
            self.show_device_table(False),
            FOOTNOTE_DEVICE_SHOW_MAIN,
        )
        unknown_devices = self.db.select("devices", type="unknown")
        if len(unknown_devices) > 0:
            msg += format_paragraph(
                TITLE_SOME_UNKNOWN_DEVICES,
                self.show_device_table(True),
                FOOTNOTE_SOME_UNKNOWN_DEVICES,
            )
        return msg

    def parse_device_set(
        self, requester, device_set, allowed_device_set=None, allow_empty=False
    ):
        devices = []
        if "," in device_set:
            for subset in device_set.split(","):
                subset_devices = self.parse_device_set(
                    requester, subset, allow_empty=True
                )
                if subset_devices is None:
                    return None
                devices += subset_devices
        elif device_set == "server":
            devices = [self.get_complete_device_info(self.server_mac)]
        else:
            username = requester.get_username()
            if not username:
                return None  # client already disconnected, give up
            # check keywords
            sql = None
            if device_set is None or device_set == "my-nodes":
                sql = MY_NODES_QUERY % username
            elif device_set in DEVICE_SET_QUERIES:
                sql = DEVICE_SET_QUERIES[device_set]
            if sql is not None:
                # retrieve devices from database
                device_macs = [record[0] for record in self.db.execute(sql)]
            else:
                # otherwise a specific device is requested by name
                dev_name = device_set
                dev_info = self.get_device_info(requester, dev_name)
                if dev_info is None:
                    return None
                device_macs = [dev_info.mac]
            # get complete devices info
            devices = [self.get_complete_device_info(mac) for mac in device_macs]
        # verify selected devices are allowed
        if allowed_device_set is not None:
            allowed_dev_names = set(
                d.name for d in self.parse_device_set(requester, allowed_device_set)
            )
            for d in devices:
                if d.name not in allowed_dev_names:
                    requester.stderr.write(
                        f"Invalid value '{device_set}'; allowed devices belong to"
                        f" '{allowed_device_set}'\n"
                    )
                    return None
        if len(devices) == 0 and not allow_empty:
            requester.stderr.write(
                "No matching devices found! (tip: walt help show node-ownership)\n"
            )
            return None
        return sorted(devices)

    def as_device_set(self, names):
        return ",".join(sorted(names))

    def develop_device_set(self, requester, device_set):
        devices = self.parse_device_set(requester, device_set)
        if devices is None:
            return None
        return self.as_device_set(d.name for d in devices)

    def get_connectivity_info(self, device_mac):
        # we look for a record where mac1 or mac2 equals device_mac
        records = list(self.db.select("topology", mac1=device_mac))
        records += list(self.db.select("topology", mac2=device_mac))
        if len(records) != 1:
            return (None, None)
        record = records[0]
        if record.mac1 == device_mac:
            switch_mac, switch_port = record.mac2, record.port2
        else:
            switch_mac, switch_port = record.mac1, record.port1
        switch_info = self.get_complete_device_info(switch_mac)
        return switch_info, switch_port

    def prepare_netsetup(self):
        # force-create the chain WALT and assert it is empty
        do("iptables --new-chain WALT")
        do("iptables --flush WALT")
        do("iptables --append WALT --jump DROP")
        # allow traffic on the bridge (virtual <-> physical nodes)
        do(
            "iptables --append FORWARD "
            "--in-interface walt-net --out-interface walt-net "
            "--jump ACCEPT"
        )
        # allow connections back to WalT
        do(
            "iptables --append FORWARD "
            "--out-interface walt-net --match state --state RELATED,ESTABLISHED "
            "--jump ACCEPT"
        )
        # jump to WALT chain for other traffic
        do("iptables --append FORWARD --in-interface walt-net --jump WALT")
        # NAT nodes traffic that is allowed to go outside
        do(
            "iptables --table nat --append POSTROUTING "
            "! --out-interface walt-net --source %s "
            "--jump MASQUERADE"
            % str(get_walt_subnet())
        )
        # Set the configuration of all NAT-ed devices
        for device_info in self.db.execute("""\
                SELECT ip FROM devices
                WHERE COALESCE((conf->'netsetup')::int, 0) = %d;
                """ % NetSetup.NAT):
            do("iptables --insert WALT --source '%s' --jump ACCEPT" % device_info.ip)

    def cleanup_netsetup(self):
        # drop rules set by prepare_netsetup
        do(
            "iptables --table nat --delete POSTROUTING "
            "! --out-interface walt-net --source %s "
            "--jump MASQUERADE"
            % str(get_walt_subnet())
        )
        do("iptables --delete FORWARD --in-interface walt-net --jump WALT")
        do(
            "iptables --delete FORWARD "
            "--out-interface walt-net --match state --state RELATED,ESTABLISHED "
            "--jump ACCEPT"
        )
        do(
            "iptables --delete FORWARD "
            "--in-interface walt-net --out-interface walt-net "
            "--jump ACCEPT"
        )
        do("iptables --flush WALT")
        do("iptables --delete-chain WALT")

    def prepare_ssh_access_for_ip(self, ip):
        cmd = CMD_ADD_SSH_KNOWN_HOST % dict(ip=ip)
        do(cmd, shell=True)

    def prepare_ssh_access(self, requester, device_set):
        devices = self.parse_device_set(requester, device_set)
        if devices is None:
            return
        for device in devices:
            self.prepare_ssh_access_for_ip(device.ip)
