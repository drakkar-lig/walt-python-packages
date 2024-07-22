import numpy as np

from walt.common.formatting import format_paragraph
from walt.common.netsetup import NetSetup
from walt.server.tools import np_columnate

NODE_SHOW_QUERY = """
    WITH powersave_macs AS (
        SELECT n.mac
        FROM nodes n, topology t, poeoff po
        WHERE po.reason = 'powersave' AND (
            (n.mac = t.mac1 AND t.mac2 = po.mac AND t.port2 = po.port) OR
            (n.mac = t.mac2 AND t.mac1 = po.mac AND t.port1 = po.port)))
    SELECT  d.name as name, n.model as model,
        split_part(n.image, '/', 1) as image_owner,
        split_part(n.image, '/', 2) as image_name,
        d.virtual as virtual, d.mac as mac,
        d.ip as ip, COALESCE((d.conf->'netsetup')::int, 0) as netsetup_int,
        (CASE WHEN n.mac in (SELECT mac FROM powersave_macs)
              THEN 1 ELSE 0 END) as powersave,
        false as booted, 'physical' as type,
        '' as image, '' as clonable_image_link, '' as netsetup
    FROM devices d, nodes n
    WHERE   d.type = 'node'
    AND     d.mac = n.mac
    ORDER BY image_owner, name;"""

MSG_USING_NO_NODES = """\
You currently do not own any nodes."""

MSG_RERUN_WITH_ALL = """\
Re-run with --all to see all available nodes."""

MSG_TIP = """\
Type `walt help show node-ownership` for help."""

TITLE_NODE_SHOW_FREE_NODES_PART = """\
The following nodes are currently free:"""

TITLE_NODE_SHOW_USER_NODES_PART = """\
You currently own the following nodes:"""

TITLE_NODE_SHOW_OTHER_NODES_PART = """\
The following nodes currently belong to other users:"""

MSG_NO_NODES = """\
No nodes detected!"""

MSG_NO_OTHER_NODES = """\
No other nodes were detected (apart from the ones listed above)."""


def generate_table(title, footnote, records, *col_titles):
    col_titles = list(col_titles)
    table = records[col_titles]
    return format_paragraph(title, np_columnate(table), footnote)


def user_subsets(res, username):
    # compute user, free and other subsets
    mask_u = (res.image_owner == username)        # user
    mask_f = (res.image_owner == "waltplatform")  # free
    mask_o = ~mask_u & ~mask_f                    # other
    return res[mask_u], res[mask_f], res[mask_o]


def show(manager, username, show_all, names_only):
    res = manager.db.execute(NODE_SHOW_QUERY)
    # if returning only names, we can return quickly
    if names_only:
        if show_all:
            names = res.name
        else:
            res_user, res_free, res_other = user_subsets(res, username)
            names = res_user.name
        return "\n".join(names)
    # compute res.type (the db query initialized to "physical" by default)
    mask_virt_mac = np.char.startswith(res.mac.astype(str), "52:54:00")
    mask_virt = res.virtual.astype(bool)
    res.type[mask_virt & mask_virt_mac] = "virtual"
    res.type[mask_virt & ~mask_virt_mac] = "vpn"
    # compute compact res.image name
    res.image = np.char.replace(res.image_name.astype(str), ":latest", "")
    # compute res.clonable_image_link
    res.clonable_image_link = ("walt:" + res.image_owner + "/" + res.image)
    # compute res.netsetup label
    res.netsetup[res.netsetup_int == NetSetup.LAN] = "LAN"
    res.netsetup[res.netsetup_int == NetSetup.NAT] = "NAT"
    # compute res.booted
    mask_booted = np.isin(res.mac, list(manager.get_booted_macs()))
    mask_powersave = (res.powersave == 1)
    res.booted[mask_booted] = "yes"
    res.booted[~mask_booted & mask_powersave] = "no (powersave)"
    res.booted[~mask_booted & ~mask_powersave] = "NO"
    # compute "user", "free" and "other" subsets
    res_user, res_free, res_other = user_subsets(res, username)
    # format output
    result_msg = ""
    footnotes = ()
    if len(res_user) == 0 and not show_all:
        footnotes += (MSG_USING_NO_NODES, MSG_RERUN_WITH_ALL)
    elif len(res_other) + len(res_user) + len(res_free) == 0:
        footnotes += (MSG_NO_NODES,)
    else:
        if len(res_user) > 0:
            # display nodes of requester
            if not show_all:
                footnotes += (MSG_RERUN_WITH_ALL,)
            result_msg += generate_table(
                TITLE_NODE_SHOW_USER_NODES_PART,
                None,
                res_user,
                "name",
                "type",
                "model",
                "image",
                "ip",
                "netsetup",
                "booted",
            )
        if show_all:
            if len(res_free) + len(res_other) == 0:
                footnotes += (MSG_NO_OTHER_NODES,)
            if len(res_free) > 0:
                # display free nodes
                result_msg += generate_table(
                    TITLE_NODE_SHOW_FREE_NODES_PART,
                    None,
                    res_free,
                    "name",
                    "type",
                    "model",
                    "ip",
                    "netsetup",
                    "booted",
                )
            if len(res_other) > 0:
                # display nodes of other users
                result_msg += generate_table(
                    TITLE_NODE_SHOW_OTHER_NODES_PART,
                    None,
                    res_other,
                    "name",
                    "type",
                    "model",
                    "image_owner",
                    "clonable_image_link",
                    "ip",
                    "netsetup",
                    "booted",
                )
    footnotes += (MSG_TIP,)
    return result_msg + "\n".join(footnotes)
