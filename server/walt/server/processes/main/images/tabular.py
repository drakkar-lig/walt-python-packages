import numpy as np


COPIED_FIELDS = {
    "id": "image_id",
    "name": "name",
    "user": "user",
    "fullname": "fullname",
    "in_use": "in_use",
    "created": "created_at",
    "compatibility:compact": "node_models_desc",
}


def compute_comp_tuple_field(work_data):
    return np.fromiter(
        (tuple(data.node_models) for data in work_data),
        dtype=object
    )


def compute_clonable_link(work_data):
    return "walt:" + work_data.user + "/" + work_data.name


COMPUTED_FIELDS = {
    "compatibility:tuple": compute_comp_tuple_field,
    "clonable_link": compute_clonable_link,
}


def compute_field(work_data, field):
    assert field in COMPUTED_FIELDS
    return COMPUTED_FIELDS[field](work_data)


def objects_dtype(fields):
    return [(k, object) for k in fields]


def get_user_tabular_data(
    db, images_store, requester, username, refresh, fields,
    may_clone_default_images=True
):
    if refresh:
        images_store.resync_from_registry(rescan=True)
    images_db_info = db.get_user_images(username)
    if len(images_db_info) == 0 and may_clone_default_images:
        # new user, try to make his life easier by cloning
        # default images of node models present on the platform.
        valid, updated, _ = images_store.get_clones_of_default_images(
                                requester, "all-nodes")
        if valid and updated:
            # succeeded, restart the process to get info about new images
            return get_user_tabular_data(
                db,
                images_store,
                requester,
                username,
                refresh,
                fields,
                may_clone_default_images=False,
            )
    return _get_tabular_data_for_images(images_store, images_db_info, fields)


def get_all_tabular_data(db, images_store, refresh, fields):
    if refresh:
        images_store.resync_from_registry(rescan=True)
    images_db_info = db.get_all_images()
    return _get_tabular_data_for_images(images_store, images_db_info, fields)


def _get_tabular_data_for_images(images_store, images_db_info, fields):
    tabular_data = np.empty(len(images_db_info), objects_dtype(fields))
    if len(images_db_info) > 0:
        fullnames = images_db_info["fullname"]
        images = images_store.get_images_per_fullnames(fullnames)
        image_fields = ["name", "fullname", "user"]
        metadata = images_store.registry.get_multiple_metadata(fullnames)
        metadata_fields = list(metadata[0].keys())
        work_fields = metadata_fields + image_fields + ["in_use"]
        work_data = np.empty(len(images_db_info), objects_dtype(work_fields))
        work_data[image_fields] = np.fromiter(
                ((image.name, image.fullname, image.user) for image in images),
                objects_dtype(image_fields)
        )
        work_data[metadata_fields] = np.fromiter(
                (tuple(m.values()) for m in metadata),
                objects_dtype(metadata_fields)
        )
        work_data["in_use"] = images_db_info["in_use"]
        work_data = work_data.view(np.recarray)
        # copy fields that are already available
        copy_dst_fields = [f for f in fields if f in set(COPIED_FIELDS)]
        copy_src_fields = [COPIED_FIELDS[f] for f in copy_dst_fields]
        tabular_data[copy_dst_fields] = work_data[copy_src_fields]
        # compute other fields
        computed_fields = [f for f in fields if f not in set(copy_dst_fields)]
        for field in computed_fields:
            tabular_data[field] = compute_field(work_data, field)
    return tabular_data.view(np.recarray)
