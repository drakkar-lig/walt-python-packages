IMAGE_FIELDS = {
    "id": lambda db_info, image: image.image_id,
    "name": lambda db_info, image: image.name,
    "fullname": lambda db_info, image: image.fullname,
    "in_use": lambda db_info, image: db_info.in_use,
    "created": lambda db_info, image: image.metadata["created_at"],
    "compatibility:compact": lambda db_info, image: image.metadata["node_models_desc"],
    "compatibility:tuple": lambda db_info, image: tuple(image.metadata["node_models"]),
}


def compute_field(db_info, image, field):
    assert field in IMAGE_FIELDS
    return IMAGE_FIELDS[field](db_info, image)


def get_tabular_data(
    db, images, requester, username, refresh, fields, may_clone_default_images=True
):
    if refresh:
        images.resync_from_registry(rescan=True)
    images_db_info = db.get_user_images(username)
    tabular_data = []
    for db_info in images_db_info:
        image = images[db_info.fullname]
        tabular_data.append(
            list(compute_field(db_info, image, field) for field in fields)
        )
    if len(tabular_data) == 0 and may_clone_default_images:
        # new user, try to make his life easier by cloning
        # default images of node models present on the platform.
        valid, updated, _ = images.get_clones_of_default_images(requester, "all-nodes")
        if valid and updated:
            # succeeded, restart the process to get info about new images
            return get_tabular_data(
                db,
                images,
                requester,
                username,
                refresh,
                fields,
                may_clone_default_images=False,
            )
    return tabular_data
