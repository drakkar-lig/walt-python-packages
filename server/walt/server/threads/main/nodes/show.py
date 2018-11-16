from walt.server.threads.main.network.netsetup import NetSetup
from walt.server.tools import format_paragraph, columnate

NODE_SHOW_QUERY = """
    SELECT  d.name as name, n.model as model,
        split_part(n.image, '/', 1) as image_owner,
        split_part(n.image, '/', 2) as image_name,
        i.ready as image_ready,
        d.ip as ip, n.netsetup as netsetup,
        (case when n.booted then 'yes' else 'NO' end) as booted
    FROM devices d, nodes n, images i
    WHERE   d.type = 'node'
    AND     d.mac = n.mac
    AND     n.image = i.fullname
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

TITLE_NODE_SHOW_NOT_READY_NODES_PART = """\
The following nodes were detected but are not available for now:
the startup OS image they will boot is being downloaded."""

MSG_NO_NODES = """\
No nodes detected!"""

MSG_NO_OTHER_NODES = """\
No other nodes were detected (apart from the ones listed above)."""

def short_image_name(image_name):
    if image_name.endswith(':latest'):
        image_name = image_name[:-7]
    return image_name

def show(db, username, show_all):
    res_user, res_free, res_other, res_not_ready = [], [], [], []
    res = db.execute(NODE_SHOW_QUERY)
    for record in res:
        if not record.image_ready:
            res_not_ready.append(record)
        else:
            if record.image_owner == username:
                res_user.append(record)
            elif record.image_owner == 'waltplatform':
                res_free.append(record)
            else:
                res_other.append(record)
    result_msg = ''
    if len(res_user) == 0 and not show_all:
        return MSG_USING_NO_NODES + '\n' + MSG_RERUN_WITH_ALL
    if len(res_user) > 0:
        # display nodes of requester
        footnote = None
        if not show_all:
            footnote = MSG_RERUN_WITH_ALL
        table = [(record.name, record.model,
                  short_image_name(record.image_name), record.ip,
                  NetSetup(record.netsetup).readable_string(), record.booted)
                 for record in res_user]
        header = ['name', 'model', 'image', 'ip', 'netsetup', 'booted']
        result_msg += format_paragraph(
                        TITLE_NODE_SHOW_USER_NODES_PART,
                        columnate(table, header=header),
                        footnote)
    if not show_all:
        return result_msg
    if len(res_free) > 0:
        # display free nodes
        footnote = None
        table = [(record.name, record.model, record.ip,
                  NetSetup(record.netsetup).readable_string(), record.booted)
                 for record in res_free]
        header = ['name', 'model', 'ip', 'netsetup', 'booted']
        result_msg += format_paragraph(
                        TITLE_NODE_SHOW_FREE_NODES_PART,
                        columnate(table, header=header),
                        footnote)
    if len(res_other) + len(res_user) + len(res_free) + len(res_not_ready) == 0:
        return MSG_NO_NODES + '\n'
    if len(res_free) + len(res_other) + len(res_not_ready) == 0:
        result_msg += MSG_NO_OTHER_NODES + '\n'
    else:
        if len(res_other) > 0:
            # display nodes of other users
            table = [(record.name, record.model, record.image_owner,
                      'server:%s/%s' % \
                        (record.image_owner, short_image_name(record.image_name)),
                      record.ip, NetSetup(record.netsetup).readable_string(),
                      record.booted)
                     for record in res_other]
            header = ['name', 'model', 'image_owner', 'clonable_image_link', 'ip', 'netsetup', 'booted']
            result_msg += format_paragraph(
                        TITLE_NODE_SHOW_OTHER_NODES_PART,
                        columnate(table, header=header))
        if len(res_not_ready) > 0:
            # display nodes whose image is currently being downloaded
            table = [(record.name, record.model, record.ip,
                      NetSetup(record.netsetup).readable_string())
                     for record in res_not_ready]
            header = ['name', 'model', 'ip', 'netsetup']
            result_msg += format_paragraph(
                        TITLE_NODE_SHOW_NOT_READY_NODES_PART,
                        columnate(table, header=header))
    return result_msg

