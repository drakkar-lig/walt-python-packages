from walt.common.formatting import columnate

MSG_WS_IS_EMPTY="""\
Your working set is empty.
Use 'walt image search [<keyword>]' to search for images
you could build upon.
Then use 'walt image clone <clonable_link>' to clone them
into your working set.
"""

def show(db, images, requester, username, refresh, names_only):
    if refresh:
        images.resync_from_repository(rescan=True)
    images_db_info = db.get_user_images(username)
    if names_only:
        fullnames = (db_info.fullname for db_info in images_db_info)
        tabular_data = [ (images[fullname].name,) for fullname in fullnames ]
    else:
        tabular_data = []
        for db_info in db.get_user_images(username):
            image = images[db_info.fullname]
            metadata = image.metadata
            tabular_data.append([
                        image.name,
                        str(db_info.in_use),
                        metadata['created_at'],
                        str(db_info.ready),
                        metadata['node_models_desc']])
    if len(tabular_data) == 0:
        # new user, try to make his life easier by cloning
        # default images of node models present on the platform.
        if images.clone_default_images(requester):
            # succeeded, restart the process to print new images
            return show(db, images, requester, username, refresh, names_only)
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
