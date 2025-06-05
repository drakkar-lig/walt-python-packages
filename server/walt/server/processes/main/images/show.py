import numpy as np

from walt.common.formatting import format_paragraph
from walt.server.processes.main.images.tabular import (
        get_user_tabular_data,
        get_all_tabular_data,
)
from walt.server.tools import np_columnate

MSG_WS_IS_EMPTY = """\
Your working set is empty."""

MSG_RERUN_WITH_ALL = """\
Re-run with --all to see all OS images on this platform."""

MSG_TIP_CLONE = """\
Use 'walt image clone <clonable_link>' to clone an image
into your working set."""

MSG_TIP_SEARCH = """\
Use 'walt image search [<keyword>]' to search for images
on remote registries."""

TITLE_IMAGE_SHOW_USER_IMAGES_PART = """\
Your working set is made of the following images:"""

TITLE_IMAGE_SHOW_OTHER_IMAGES_PART = """\
Other users of this platform have created the following images:"""

TITLE_IMAGE_SHOW_DEFAULT_IMAGES_PART = """\
The following are default OS images:"""

MSG_NO_IMAGES = """\
No OS images found!"""


def user_subsets(data, username):
    # user: images of requester
    mask_u = (data.user == username)
    # default: images of "waltplatform" with "-default" suffix
    mask_d = (data.user == "waltplatform")
    mask_d &= np.char.endswith(data.name.astype(str), "-default")
    # other: other images
    mask_o = ~mask_u & ~mask_d
    return data[mask_u], data[mask_o], data[mask_d]


def generate_table(title, footnote, records, *col_titles):
    col_titles = list(col_titles)
    table = records[col_titles]
    return format_paragraph(title, np_columnate(table), footnote)


def get_tabular_data(db, images_store, requester,
                     username, refresh,
                     may_clone_default_images=True):
    fields = ("user", "name", "in_use", "created",
              "compatibility:compact", "clonable_link")
    data = get_all_tabular_data(db, images_store, refresh, fields)
    res_user, res_other, res_default = user_subsets(data, username)
    if len(res_user) == 0 and may_clone_default_images:
        # new user, try to make his life easier by cloning
        # default images of node models present on the platform.
        valid, updated, _ = images_store.get_clones_of_default_images(
                                requester, "all-nodes")
        if valid and updated:
            # succeeded, restart the process to get info about new images
            return get_tabular_data(
                db,
                images_store,
                requester,
                username,
                refresh=False,  # already done at 1st iteration
                may_clone_default_images=False,
            )
    return res_user, res_other, res_default


def show(requester, images_manager, username, show_all, names_only, refresh):
    db = images_manager.db
    images_store = images_manager.store
    # note: --names-only and --all are mutually exclusive, and this is
    # verified on client side.
    if names_only:
        fields = ("name",)
        data = get_user_tabular_data(db, images_store, requester,
                                     username, refresh, fields)
        return (data.name + "\n").sum().rstrip("\n")
    # compute "user", "other" and "default" subsets
    res_user, res_other, res_default = get_tabular_data(
            db, images_store, requester, username, refresh)
    # format output
    result_msg = ""
    footnotes = ()
    if not show_all and len(res_other) + len(res_default) > 0:
        footnotes += (MSG_RERUN_WITH_ALL,)
    if len(res_user) == 0 and not show_all:
        footnotes = (MSG_WS_IS_EMPTY,) + footnotes
    elif len(res_other) + len(res_user) + len(res_default) == 0:
        footnotes = (MSG_NO_IMAGES,) + footnotes
    else:
        if len(res_user) > 0:
            # display images of requester
            result_msg += generate_table(
                TITLE_IMAGE_SHOW_USER_IMAGES_PART,
                None,
                res_user,
                "name",
                "in_use",
                "created",
                "compatibility:compact",
            )
        if show_all:
            if len(res_other) > 0:
                # display images of other users
                result_msg += generate_table(
                    TITLE_IMAGE_SHOW_OTHER_IMAGES_PART,
                    None,
                    res_other,
                    "user",
                    "name",
                    "created",
                    "clonable_link",
                )
            if len(res_default) > 0:
                # display default images
                result_msg += generate_table(
                    TITLE_IMAGE_SHOW_DEFAULT_IMAGES_PART,
                    None,
                    res_default,
                    "name",
                    "created",
                    "clonable_link",
                )
            if len(res_other) + len(res_default) > 0:
                footnotes += (MSG_TIP_CLONE,)
            footnotes += (MSG_TIP_SEARCH,)
    return result_msg + "\n".join(footnotes)
