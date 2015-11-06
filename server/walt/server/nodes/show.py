from walt.server.tools import format_paragraph

# the split_part() expression below allows to show only
# the image tag to the user (instead of the full docker name).
USER_NODES_QUERY = """
    SELECT  d.name as name, d.type as type,
            split_part(n.image, ':', 2) as image,
            d.ip as ip,
            (case when d.reachable = 1 then 'yes' else 'NO' end) as reachable
    FROM devices d, nodes n
    WHERE   d.mac = n.mac
    AND     split_part(n.image, '/', 1) = '%s'
    ORDER BY name;"""

OTHER_NODES_QUERY = """
    SELECT  d.name as name, d.type as type,
            split_part(n.image, '/', 1) as image_owner,
            'server:' ||
            split_part(n.image, '/', 1) ||
            '/' ||
            split_part(n.image, ':', 2) as clonable_image_link,
            d.ip as ip,
            (case when d.reachable = 1 then 'yes' else 'NO' end) as reachable
    FROM devices d, nodes n, images i
    WHERE   d.mac = n.mac
    AND     n.image = i.fullname
    AND     i.ready = True
    AND     split_part(n.image, '/', 1) != '%s'
    ORDER BY image_owner, name;"""

NODES_IMAGE_NOT_READY_QUERY = """
    SELECT  d.name as name, d.type as type,
            split_part(n.image, '/', 1) as image_owner,
            'server:' ||
            split_part(n.image, '/', 1) ||
            '/' ||
            split_part(n.image, ':', 2) as clonable_image_link,
            d.ip as ip
    FROM devices d, nodes n, images i
    WHERE   d.mac = n.mac
    AND     n.image = i.fullname
    AND     i.ready = False
    ORDER BY image_owner, name;"""

MSG_USING_NO_NODES = """\
You are currently using no nodes. (tip: walt --help-about node-terminology)"""

MSG_RERUN_WITH_ALL = """\
Re-run with --all to see all deployable nodes."""

TITLE_NODE_SHOW_USER_NODES_PART = """\
Nodes with an image that you own:"""

TITLE_NODE_SHOW_OTHER_NODES_PART = """\
The following nodes are likely to be used by other users, since you do
not own the image deployed on them."""

TITLE_NODE_SHOW_NOT_READY_NODES_PART = """\
The following nodes were detected but are not available for now:
the OS image they will boot is being downloaded."""

MSG_NO_NODES = """\
No nodes detected!"""

MSG_NO_OTHER_NODES = """\
No other nodes were detected (apart from the ones listed above)."""

def show(db, requester, show_all):
    result_msg = ''
    # get nodes of requester
    # (i.e. deployed with an image that the requester owns)
    user_nodes_query = USER_NODES_QUERY % requester.username
    res_user = db.execute(user_nodes_query).fetchall()
    if len(res_user) == 0 and not show_all:
        return MSG_USING_NO_NODES + '\n' + MSG_RERUN_WITH_ALL
    if len(res_user) > 0:
        footnote = None
        if not show_all:
            footnote = MSG_RERUN_WITH_ALL
        result_msg += format_paragraph(
                        TITLE_NODE_SHOW_USER_NODES_PART,
                        db.pretty_printed_resultset(res_user),
                        footnote)
    if not show_all:
        return result_msg
    # get nodes of other users
    other_nodes_query = OTHER_NODES_QUERY % requester.username
    res_other = db.execute(other_nodes_query).fetchall()
    # get nodes whose image is currently being downloaded
    not_ready_nodes_query = NODES_IMAGE_NOT_READY_QUERY
    res_not_ready = db.execute(not_ready_nodes_query).fetchall()
    if len(res_other) == 0 and len(res_user) and len(res_not_ready) == 0:
        return MSG_NO_NODES + '\n'
    if len(res_other) == 0 and len(res_not_ready) == 0:
        result_msg += MSG_NO_OTHER_NODES + '\n'
    else:
        if len(res_other) > 0:
            result_msg += format_paragraph(
                        TITLE_NODE_SHOW_OTHER_NODES_PART,
                        db.pretty_printed_resultset(res_other))
        if len(res_not_ready) > 0:
            result_msg += format_paragraph(
                        TITLE_NODE_SHOW_NOT_READY_NODES_PART,
                        db.pretty_printed_resultset(res_not_ready))
    return result_msg

