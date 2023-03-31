from walt.common.netsetup import NetSetup
from walt.common.formatting import format_paragraph, columnate

NODE_SHOW_QUERY = """
    SELECT  d.name as name, n.model as model,
        split_part(n.image, '/', 1) as image_owner,
        split_part(n.image, '/', 2) as image_name,
        d.virtual as virtual, d.mac as mac,
        d.ip as ip, COALESCE((d.conf->'netsetup')::int, 0) as netsetup,
        (case when n.booted then 'yes' else 'NO' end) as booted
    FROM devices d, nodes n
    WHERE   d.type = 'node'
    AND     d.mac = n.mac
    ORDER BY image_owner, name;"""

MSG_USING_NO_NODES = """\
You are currently using no nodes. (tip: walt help show node-terminology)"""

MSG_RERUN_WITH_ALL = """\
Re-run with --all to see all available nodes."""

TITLE_NODE_SHOW_FREE_NODES_PART = """\
The following nodes are free (they boot a default image):"""

TITLE_NODE_SHOW_USER_NODES_PART = """\
The following nodes are running one of your images:"""

TITLE_NODE_SHOW_OTHER_NODES_PART = """\
The following nodes are likely to be used by other users, since you do
not own the image they boot."""

MSG_NO_NODES = """\
No nodes detected!"""

MSG_NO_OTHER_NODES = """\
No other nodes were detected (apart from the ones listed above)."""

def short_image_name(image_name):
    if image_name.endswith(':latest'):
        image_name = image_name[:-7]
    return image_name

def node_type(mac, virtual):
    if mac.startswith('52:54:00'):
        if virtual:
            return 'virtual'
        else:
            return 'vpn'
    else:
        return 'physical'

def get_table_value(record, col_title):
    if col_title == 'type':
        return node_type(record.mac, record.virtual)
    elif col_title == 'image':
        return short_image_name(record.image_name)
    elif col_title == 'netsetup':
        return NetSetup(record.netsetup).readable_string()
    elif col_title == 'clonable_image_link':
        return 'walt:%s/%s' % (record.image_owner, short_image_name(record.image_name))
    else:
        return getattr(record, col_title)

def generate_table(title, footnote, records, *col_titles):
    table = [ tuple(get_table_value(record, col_title) for col_title in col_titles) \
              for record in records ]
    header = list(col_titles)
    return format_paragraph(title, columnate(table, header=header), footnote)

def show(db, username, show_all, names_only):
    res_user, res_free, res_other = [], [], []
    res = db.execute(NODE_SHOW_QUERY)
    for record in res:
        if record.image_owner == username:
            res_user.append(record)
        elif record.image_owner == 'waltplatform':
            res_free.append(record)
        else:
            res_other.append(record)
    if names_only:
        if show_all:
            all_records = res_user + res_free + res_other
        else:
            all_records = res_user
        return "\n".join(record.name for record in all_records)
    result_msg = ''
    if len(res_user) == 0 and not show_all:
        return MSG_USING_NO_NODES + '\n' + MSG_RERUN_WITH_ALL
    if len(res_user) > 0:
        # display nodes of requester
        footnote = None
        if not show_all:
            footnote = MSG_RERUN_WITH_ALL
        result_msg += generate_table(TITLE_NODE_SHOW_USER_NODES_PART, footnote, res_user,
                        'name', 'type', 'model', 'image', 'ip', 'netsetup', 'booted')
    if not show_all:
        return result_msg
    if len(res_free) > 0:
        # display free nodes
        result_msg += generate_table(TITLE_NODE_SHOW_FREE_NODES_PART, None, res_free,
                        'name', 'type', 'model', 'ip', 'netsetup', 'booted')
    if len(res_other) + len(res_user) + len(res_free) == 0:
        return MSG_NO_NODES + '\n'
    if len(res_free) + len(res_other) == 0:
        result_msg += MSG_NO_OTHER_NODES + '\n'
    else:
        if len(res_other) > 0:
            # display nodes of other users
            result_msg += generate_table(TITLE_NODE_SHOW_OTHER_NODES_PART, None, res_other,
                            'name', 'type', 'model', 'image_owner', 'clonable_image_link', 'ip', 'netsetup', 'booted')
    return result_msg

