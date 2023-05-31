from walt.common.formatting import columnate, format_paragraph
from walt.common.netsetup import NetSetup

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
        d.ip as ip, COALESCE((d.conf->'netsetup')::int, 0) as netsetup,
        (CASE WHEN n.booted THEN 'yes'
              WHEN n.mac in (SELECT mac FROM powersave_macs) THEN 'no (powersave)'
              ELSE 'NO' END) as booted
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


def short_image_name(image_name):
    if image_name.endswith(":latest"):
        image_name = image_name[:-7]
    return image_name


def node_type(mac, virtual):
    if mac.startswith("52:54:00"):
        if virtual:
            return "virtual"
        else:
            return "vpn"
    else:
        return "physical"


def get_table_value(record, col_title):
    if col_title == "type":
        return node_type(record.mac, record.virtual)
    elif col_title == "image":
        return short_image_name(record.image_name)
    elif col_title == "netsetup":
        return NetSetup(record.netsetup).readable_string()
    elif col_title == "clonable_image_link":
        return "walt:%s/%s" % (record.image_owner, short_image_name(record.image_name))
    else:
        return getattr(record, col_title)


def generate_table(title, footnote, records, *col_titles):
    table = [
        tuple(get_table_value(record, col_title) for col_title in col_titles)
        for record in records
    ]
    header = list(col_titles)
    return format_paragraph(title, columnate(table, header=header), footnote)


def show(db, username, show_all, names_only):
    res_user, res_free, res_other = [], [], []
    res = db.execute(NODE_SHOW_QUERY)
    for record in res:
        if record.image_owner == username:
            res_user.append(record)
        elif record.image_owner == "waltplatform":
            res_free.append(record)
        else:
            res_other.append(record)
    if names_only:
        if show_all:
            all_records = res_user + res_free + res_other
        else:
            all_records = res_user
        return "\n".join(record.name for record in all_records)
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
