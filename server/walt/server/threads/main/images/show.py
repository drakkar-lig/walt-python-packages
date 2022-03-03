from walt.server.tools import format_node_models_list
from walt.common.formatting import columnate

MSG_WS_IS_EMPTY="""\
Your working set is empty.
Use 'walt image search [<keyword>]' to search for images
you could build upon.
Then use 'walt image clone <clonable_link>' to clone them
into your working set.
"""

def show(db, images, requester, refresh, names_only):
    username = requester.get_username()
    if not username:
        return None     # client already disconnected, give up
    if refresh:
        images.refresh()
    tabular_data = []
    for image in images.values():
        if image.user != username:
            continue
        created_at = image.created_at
        node_models = image.get_node_models()
        tabular_data.append([
                    image.name,
                    str(image.in_use),
                    created_at if created_at else 'N/A',
                    str(image.ready),
                    format_node_models_list(node_models) if node_models else 'N/A'])
    if len(tabular_data) == 0:
        # new user, try to make his life easier by cloning
        # default images of node models present on the platform.
        if images.clone_default_images(requester):
            # succeeded, restart the process to print new images
            return show(db, images, requester, refresh, names_only)
        else:
            if names_only:
                return ''
            else:
                return MSG_WS_IS_EMPTY
    if names_only:
        return '\n'.join(row[0] for row in tabular_data)
    else:
        header = [ 'Name', 'In-use', 'Created', 'Ready', 'Compatibility' ]
        return columnate(tabular_data, header)
