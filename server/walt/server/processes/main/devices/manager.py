import numpy as np
import re

from walt.common.formatting import format_paragraph
from walt.common.netsetup import NetSetup
from walt.common.tools import do, get_mac_address
from walt.server import const
from walt.server.tools import (
    get_server_ip,
    get_walt_subnet,
    ip_in_walt_network,
    np_columnate
)

NEW_NAME_ERROR_AND_GUIDELINES = """\
Failed: invalid new name.
This name must be a valid network hostname.
Only alphanumeric characters and '-' are allowed.
The 1st character must be an alphabet letter.
The name must be at least 2-chars long.
(Example: rpi-D327)
"""

# "walt device show" should not print the netsetup status for the server
# or devices outside walt-net
WALT_SUBNET = str(get_walt_subnet())
DEVICES_QUERY = f"""\
WITH infodev AS (SELECT name, ip, mac,
       CASE WHEN type = 'node' AND virtual THEN 'node (virtual)'
            WHEN type = 'node' AND mac like '52:54:00:%%' THEN 'node (vpn)'
            WHEN type = 'node' THEN 'node (physical)'
            ELSE type
       END as type,
COALESCE((conf->'netsetup')::int, 0) as int_netsetup
FROM devices)
SELECT name, ip, mac, type,
CASE WHEN type = 'server'                       THEN NULL
     WHEN ip IS NULL                            THEN NULL
     WHEN NOT ip::inet << '{WALT_SUBNET}'::cidr THEN NULL
     WHEN int_netsetup = 0                      THEN 'LAN'
     WHEN int_netsetup = 1                      THEN 'NAT'
END as netsetup
FROM infodev
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


class DevicesManager(object):
    def __init__(self, server):
        self.server = server
        self.db = server.db
        self.logs = server.logs
        self.server_mac = get_mac_address(const.WALT_INTF)
        self.server_ip = get_server_ip()
        self.netmask = str(get_walt_subnet().netmask)
        self._fw_rules = []

    def prepare(self):
        # prepare the network setup for NAT support
        self.prepare_netsetup()

    def cleanup(self):
        self.cleanup_netsetup()

    def get_server_mac(self):
        return self.server_mac

    def validate_device_name(self, requester, name):
        if self.get_device_info(None, name) is not None:
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

    def get_device_info(self, requester=None, name=None, mac=None):
        if name is not None:
            where_sql, where_values = "d.name = %s", (name,)
            err_message = f"""No device with name '{name}' found.\n"""
        elif mac is not None:
            where_sql, where_values = "d.mac = %s OR vn.vpnmac = %s", (mac, mac)
            err_message = f"""No device with mac '{mac}' found.\n"""
        else:
            raise Exception("get_device_info() needs 'name' or 'mac' parameter.")
        devices_info = self.get_multiple_device_info(where_sql, where_values)
        if len(devices_info) == 0:
            if requester is not None:
                requester.stderr.write(err_message)
            return None
        else:
            # depending on the type, return only the relevant fields
            device_info = devices_info[0]
            min_fields = ["mac", "ip", "name", "type", "conf", "in_walt_net"]
            if device_info.type == "node":
                return device_info  # all fields are relevant
            elif device_info.type == "switch":
                return device_info[min_fields + ["model"]]
            else:
                return device_info[min_fields]

    def get_multiple_device_info(self, where_sql, where_values,
                                 sortby=None, include_connectivity=False):
        # gateway, netmask and booted flag will be filled below,
        # for now this sql query just reserve a column for these attributes.
        sql = f"""
        SELECT d.*, n.image, COALESCE(n.model, s.model) as model,
            NULL as booted, '' as gateway, NULL as netmask,
            COALESCE((d.conf->'netsetup')::int, 0) as netsetup,
            d.ip::inet << '{WALT_SUBNET}'::cidr as in_walt_net
        FROM devices d
        LEFT JOIN nodes n ON d.mac = n.mac
        LEFT JOIN switches s ON d.mac = s.mac
        LEFT JOIN vpnnodes vn ON d.mac = vn.mac
        WHERE {where_sql}"""
        # if requested, we will add columns indicating the location
        # of the device in the network.
        # we look into table topology for records where mac1 or mac2
        # equals a given device mac.
        # our result will have the following columns added:
        # - fields "sw_*" describing the switch the device
        #   is connected on
        # - field "sw_port" indicating the switch port the device
        #   is connected on
        # - field "poe_error" with value NULL or an error string
        #   indicating why a PoE request is not possible
        # cte2 and cte3 allow to filter out cases where a device has
        # multiple connection points in the topology table (this may occur
        # because of an internal switch cache, when we move a device
        # from one network position to another), preferring any
        # position with flag confirmed=True.
        if include_connectivity:
            sql = f"""
            with cte0 as (
                {sql}),
            cte1 as (
                select mac1 as mac, mac2 as sw_mac, port2 as sw_port, confirmed
                from topology, cte0
                where mac1 = cte0.mac
                union
                select mac2 as mac, mac1 as sw_mac, port1 as sw_port, confirmed
                from topology, cte0
                where mac2 = cte0.mac),
            cte2 as (
                select *,
                    ROW_NUMBER() OVER(
                        PARTITION BY mac ORDER BY confirmed desc, mac) as rownum
                from cte1),
            cte3 as (
                select * from cte2 where rownum = 1
            )
            select d.*,
                   t.sw_mac, t.sw_port,
                   sw_d.ip as sw_ip,
                   sw_d.conf->'snmp.version' as sw_snmp_version,
                   sw_d.conf->'snmp.community' as sw_snmp_community,
                   CASE WHEN t.sw_port is NULL OR sw_d.ip is NULL
                          THEN 'unknown LLDP network position'
                        WHEN not COALESCE((sw_d.conf->'poe.reboots')::bool, false)
                          THEN 'forbidden on switch'
                   END as poe_error
            from cte0 d
            left join cte3 t on t.mac = d.mac
            left join devices sw_d on sw_d.mac = t.sw_mac"""
        devices_info = self.db.execute(sql, where_values)
        if devices_info.size > 0:
            nodes_mask = (devices_info.type == 'node')
            if nodes_mask.size > 0:
                # netsetup=NAT can actually be applied to all devices, not only
                # nodes. However, considering only nodes ensures these devices
                # will really boot in walt-net and the netmask + gateway pair
                # will be correct. So we only expose this information to nodes.
                devices_info.netmask[nodes_mask] = self.netmask
                nat_mask = nodes_mask & (devices_info.netsetup == NetSetup.NAT)
                devices_info.gateway[nat_mask] = self.server_ip
                booted_mask = np.isin(devices_info[nodes_mask].mac,
                        list(self.server.nodes.get_booted_macs()))
                devices_info.booted[nodes_mask] = booted_mask
            if sortby is not None:
                # workaround a strange exception sometimes thrown by
                # arr.sort(order=sortby)
                # where values of other columns of arr are compared
                # (leading to an exception when comparing dict objects)
                # although all values of "sortby" column are unique.
                if isinstance(sortby, str):
                    sortby = [sortby]
                else:
                    sortby = list(sortby)
                indices = np.argsort(devices_info[sortby], order=sortby)
                devices_info = devices_info[indices]
        return devices_info

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
        """Add or update a device in db given **args_data arguments

           Returns a boolean indicating if something really changed.
        """
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
                        "devices", line=f"renamed {db_data.name} to {name} for clarity"
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
                assert "model" in args_data
                assert "image" in args_data
                self.db.insert("nodes", **args_data)
                dtype = "node"
                details = f" model={args_data['model']}"
            else:
                dtype = "device"
                details = f" type={db_data.type}"
            info = f"name={db_data.name}{details} mac={db_data.mac} ip={db_data.ip}"
            logline = f"new {dtype}{ident_log_line} {info}"
            self.logs.platform_log("devices", line=logline)
        if modified:
            self.db.commit()
        return modified

    def show(self):
        devices, header = self.db.pretty_print_select_info(DEVICES_QUERY)
        known_devices = devices[devices.type != "unknown"]
        unknown_devices = devices[devices.type == "unknown"]
        msg = format_paragraph(
            TITLE_DEVICE_SHOW_MAIN,
            np_columnate(known_devices, header),
            FOOTNOTE_DEVICE_SHOW_MAIN,
        )
        if len(unknown_devices) > 0:
            msg += format_paragraph(
                TITLE_SOME_UNKNOWN_DEVICES,
                np_columnate(unknown_devices, header),
                FOOTNOTE_SOME_UNKNOWN_DEVICES,
            )
        return msg

    def parse_device_set(
        self, requester, device_set, allowed_device_set=None, allow_empty=False
    ):
        device_macs = self.get_device_set_macs(requester, device_set)
        if device_macs is None:
            return None
        # verify selected devices are allowed
        if allowed_device_set is not None:
            allowed_dev_macs = self.get_device_set_macs(requester, allowed_device_set)
            if len(set(device_macs) - set(allowed_dev_macs)) > 0:
                requester.stderr.write(
                    f"Invalid value '{device_set}'; allowed devices belong to"
                    f" '{allowed_device_set}'\n"
                )
                return None
        if len(device_macs) == 0:
            if not allow_empty:
                requester.stderr.write(
                    "No matching devices found! (tip: walt help show node-ownership)\n"
                )
                return None
        return self.get_multiple_device_info_for_macs(device_macs, sortby="name")

    def get_multiple_device_info_for_macs(self, device_macs, **kwargs):
        if len(device_macs) == 0:
            where_sql = "false"
        else:
            where_sql = "d.mac IN (" + ",".join(["%s"] * len(device_macs)) + ")"
        return self.get_multiple_device_info(where_sql, device_macs, **kwargs)

    def ensure_connectivity_info(self, devices):
        if isinstance(devices, np.recarray):
            if 'sw_mac' in devices.dtype.names:
                return devices  # connectivity info is already there
            device_macs = devices.mac
        else:
            device_macs = tuple(d.mac for d in devices)
        return self.get_multiple_device_info_for_macs(
                    device_macs, include_connectivity=True)

    def get_device_set_macs(self, requester, device_set):
        device_macs = []
        if "," in device_set:
            for subset in device_set.split(","):
                subset_macs = self.get_device_set_macs(requester, subset)
                if subset_macs is None:
                    return None
                device_macs += subset_macs
        elif device_set == "server":
            device_macs += [self.server_mac]
        else:
            # check keywords
            sql = None
            if device_set is None or device_set == "my-nodes":
                username = requester.get_username()
                if not username:
                    return None  # client already disconnected, give up
                sql = MY_NODES_QUERY % username
            elif device_set in DEVICE_SET_QUERIES:
                sql = DEVICE_SET_QUERIES[device_set]
            if sql is not None:
                # retrieve devices from database
                device_macs += [record[0] for record in self.db.execute(sql)]
            else:
                # otherwise a specific device is requested by name
                dev_name = device_set
                dev_info = self.get_device_info(requester, dev_name)
                if dev_info is None:
                    return None
                device_macs += [dev_info.mac]
        return device_macs

    def as_device_set(self, names):
        return ",".join(sorted(names))

    def develop_device_set(self, requester, device_set):
        devices = self.parse_device_set(requester, device_set)
        if devices is None:
            return None
        return self.as_device_set(d.name for d in devices)

    def prepare_netsetup(self):
        # force-create the chain WALT and assert it is empty
        self._fw_rules.append("iptables --new-chain WALT")
        self._fw_rules.append("iptables --flush WALT")
        self._fw_rules.append("iptables --append WALT --jump DROP")
        # allow traffic on the bridge (virtual <-> physical nodes)
        self._fw_rules.append(
            "iptables --append FORWARD "
            "--in-interface walt-net --out-interface walt-net "
            "--jump ACCEPT"
        )
        # direct the traffic going out of walt network to WALT chain
        # (see the configuration of devices having netsetup=NAT below)
        self._fw_rules.append(
            "iptables --append FORWARD "
           f"--source {WALT_SUBNET} "
         f"! --destination {WALT_SUBNET} "
            "--jump WALT"
        )
        # allow incoming traffic to the walt network if the corresponding
        # outgoing traffic was previously allowed.
        self._fw_rules.append(
            "iptables --append FORWARD "
           f"--destination {WALT_SUBNET} "
            "--match state --state RELATED,ESTABLISHED "
            "--jump ACCEPT"
        )
        # NAT nodes traffic that is allowed to go outside
        self._fw_rules.append(
            "iptables -m addrtype --table nat --append POSTROUTING "
             f"--source {WALT_SUBNET} "
           f"! --destination {WALT_SUBNET} "
            "! --dst-type LOCAL "
            "--jump MASQUERADE"
        )
        # Apply
        for rule in self._fw_rules:
            do(rule)
        # Allow devices having netsetup=NAT to exit walt network.
        # (We do not record these device-specific rules into
        # self._fw_rules because they may change before
        # cleanup_netsetup() is called.
        # The WALT chain will just be flushed instead.)
        for device_info in self.db.execute("""\
                SELECT ip FROM devices
                WHERE COALESCE((conf->'netsetup')::int, 0) = %d;
                """ % NetSetup.NAT):
            do(f"iptables --insert WALT --source '{device_info.ip}' --jump ACCEPT")

    def _invert_fw_rule(self, rule):
        return rule.replace("--insert", "--delete"
                  ).replace("--append", "--delete"
                  ).replace("--new-chain", "--delete-chain")

    def cleanup_netsetup(self):
        for rule in reversed(self._fw_rules):
            do(self._invert_fw_rule(rule))
