import uuid

from walt.server.exttools import podman
from walt.server.processes.blocking.images.tools import update_main_process_about_image
from walt.server.tools import add_image_repo


def get_commit_temp_image():
    return "localhost/walt/commit-temp:" + str(uuid.uuid4()).split("-")[0]


def commit(server, cid_or_cname, dest_fullname, tool=podman, opts=()):
    # we commit with 'docker' format to make these images compatible with
    # older walt server versions
    opts += ("-f", "docker")
    if server.registry.image_exists(dest_fullname):
        # take care not making previous version of image a dangling image
        image_tempname = get_commit_temp_image()
        args = opts + (cid_or_cname, image_tempname)
        tool.commit(*args)
        tool.rm(cid_or_cname)
        podman.rmi("-f", add_image_repo(dest_fullname))
        podman.tag(image_tempname, add_image_repo(dest_fullname))
        podman.rmi(image_tempname)
    else:
        args = opts + (cid_or_cname, add_image_repo(dest_fullname))
        tool.commit(*args)
        tool.rm(cid_or_cname)
    update_main_process_about_image(server, dest_fullname)
