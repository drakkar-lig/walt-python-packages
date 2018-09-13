from walt.server.tools import columnate, format_node_models_list

MSG_WS_IS_EMPTY="""\
Your working set is empty.
Use 'walt image search [<keyword>]' to search for images
you could build upon.
Then use 'walt image clone <clonable_link>' to clone them
into your working set.
"""

def show(db, docker, images, requester, refresh):
    username = requester.get_username()
    if not username:
        return None     # client already disconnected, give up
    if refresh:
        images.refresh()
    tabular_data = []
    for image in images.itervalues():
        if image.user != username:
            continue
        created_at = image.get_created_at()
        node_models = image.get_node_models()
        tabular_data.append([
                    image.name,
                    str(image.mounted),
                    created_at if created_at else 'N/A',
                    str(image.ready),
                    format_node_models_list(node_models)])
    if len(tabular_data) == 0:
        # new user, try to make his life easier by cloning
        # default images of node models present on the platform.
        node_models = set(n.model for n in db.select('nodes'))
        if len(node_models) == 0:   # no nodes
            return MSG_WS_IS_EMPTY
        requester.stdout.write('Cloning default images... ')
        requester.stdout.flush()
        for model in node_models:
            default_image = images.get_default_image_fullname(model)
            ws_image = username + '/' + default_image.split('/')[1]
            docker.local.tag(default_image, ws_image)
            images.register_image(ws_image, True)
        requester.stdout.write('Done.\n')
        # restart the process
        return show(db, docker, images, requester, refresh)
    header = [ 'Name', 'Mounted', 'Created', 'Ready', 'Compatibility' ]
    return columnate(tabular_data, header)
