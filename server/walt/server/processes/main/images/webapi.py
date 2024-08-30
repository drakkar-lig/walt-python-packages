import json
import numpy as np
import re

from walt.server.processes.main.images.tabular import get_all_tabular_data
from walt.server.tools import convert_query_param_value, filter_items_with_query_params

IMAGE_FIELDS = ("fullname", "user", "id", "in_use", "created", "compatibility:tuple")

PARAM_TYPES = {
    "fullname": str,
    "user": str,
    "id": str,
    "in_use": bool
}


def web_api_list_images(db, images_store, webapi_version, query_params):
    assert webapi_version == "v1"
    refresh = query_params.pop("refresh", None)
    if refresh is None:
        refresh = False
    else:
        res = convert_query_param_value(refresh, bool)
        if not res[0]:
            return res[1]
        refresh = res[1]
    images = get_all_tabular_data(db, images_store, refresh, IMAGE_FIELDS)
    res = filter_items_with_query_params(images, PARAM_TYPES, query_params)
    if not res[0]:
        return res[1]
    images = res[1]
    # remove :<suffix> from field names
    fields = images.dtype.names
    fields = tuple(re.sub(r"([^:]*):.*", r"\1", f) for f in fields)
    images.dtype.names = fields
    return {
        "code": 200,    # ok
        "num_images": len(images),
        "images": images
    }
