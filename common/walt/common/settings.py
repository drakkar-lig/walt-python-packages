import re

DISK_TEMPLATES = set(("none", "ext4", "fat32", "hybrid-boot-v", "hybrid-boot-p"))


def parse_vnode_disks_value(setting_value):
    if setting_value == 'none':
        return (True, [])
    # check global format <disk>[,<disk>[...]]
    # with each <disk> of the form '<capacity>' or
    # '<capacity>[<options>]'
    if (
        re.match(
            r"^\d+[GT](\[[^\]]*\])?(,\d+[GT](\[[^\]]*\])?)*$", setting_value
        )
        is None
    ):
        return False, f"Could not parse disks value '{setting_value}'."
    # analyse each disk spec
    _disks = []
    for disk in setting_value.split(","):
        template_name = "none"  # default template
        if '[' in disk:
            capacity, options = disk[:-1].split('[')
            for option in options.split(','):
                if len(option) > 9 and option[:9] == "template=":
                    template_name = option[9:]
                    if template_name not in DISK_TEMPLATES:
                        return (
                            False,
                            f"Disk template must be one of: {' '.join(DISK_TEMPLATES)}"
                        )
                else:
                    return (
                        False,
                        f"'{option}' is not a valid disk option.",
                    )
        else:
            capacity = disk
        cap_gigabytes = int(capacity[:-1])
        if capacity[-1] == "T":
            cap_gigabytes *= 1000
        _disks.append((cap_gigabytes, template_name))
    return (True, _disks)


def parse_vnode_networks_value(setting_value):
    # check global format <network>[,<network>[...]]
    # with each <network> of the form '<network-name>' or
    # '<network-name>[<restrictions>]'
    if (
        re.match(
            r"^[a-z][a-z\-]*(\[[^\]]*\])?(,[a-z][a-z\-]*(\[[^\]]*\])?)*$", setting_value
        )
        is None
    ):
        return False, f"Could not parse networks value '{setting_value}'."
    # both networks and restrictions are separated with a coma, so we have to be
    # careful. first, by filtering out the restrictions enclosed in square brackets, we
    # can isolate the network names
    network_names = "".join(re.split(r"\[[^\]]*\]", setting_value)).split(",")
    networks_info = {}
    # then we can iterate to check the optional restrictions
    for network_name in network_names:
        networks_info[network_name] = {}
        if (
            len(network_name) < len(setting_value)
            and setting_value[len(network_name)] == "["
        ):
            # we have restrictions on this network
            restrictions = setting_value.split("[")[1].split("]")[0]
            # check them
            for restriction in restrictions.split(","):
                if re.match(r"^lat=[0-9]+[mu]s$", restriction.lower()) is not None:
                    val = int(restriction[4:-2])
                    unit = restriction[-2].lower()
                    if unit == "m":
                        val *= 1000  # convert to microseconds
                    networks_info[network_name]["lat_us"] = val
                elif re.match(r"^bw=[0-9]+[gm]bps$", restriction.lower()) is not None:
                    val = int(restriction[3:-4])
                    unit = restriction[-4].lower()
                    if unit == "g":
                        val *= 1000  # convert to Mbps
                    networks_info[network_name]["bw_Mbps"] = val
                else:
                    return (
                        False,
                        f"'{restriction}' is not a valid network resource restriction.",
                    )
            # offset to pass to next network
            offset = len(network_name) + 1 + len(restrictions) + 1
        else:
            # offset to pass to next network
            offset = len(network_name)
        # pass to next network
        setting_value = setting_value[offset:]
        if len(setting_value) > 0:
            # pass the coma
            setting_value = setting_value[1:]
    if "walt-net" not in network_names:
        return False, "Mandatory network 'walt-net' is missing from specified networks."
    if len(set(network_names)) < len(network_names):
        return False, "Specifying twice the same network name is not allowed."
    return True, networks_info
