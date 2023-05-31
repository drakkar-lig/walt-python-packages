from subprocess import CalledProcessError

from walt.server.exttools import buildah
from walt.server.processes.blocking.images.commit import commit
from walt.server.tools import add_image_repo


def squash_image(server, image_fullname):
    cont_name = "squash:" + image_fullname
    try:
        buildah(
            "from", "--pull-never", "--name", cont_name, add_image_repo(image_fullname)
        )
    except CalledProcessError:
        print(
            "Note: walt server was probably not stopped properly and container still"
            " exists."
        )
        print("      removing container and restarting command.")
        buildah.rm(cont_name)
        buildah(
            "from", "--pull-never", "--name", cont_name, add_image_repo(image_fullname)
        )
    commit(server, cont_name, image_fullname, tool=buildah, opts=("--squash",))


# this implements walt image squash
def squash(requester, server, image_fullname):
    store = server.images.store
    image = store[image_fullname]
    in_use = image.in_use()
    image.filesystem.close()
    squash_image(server, image_fullname)
    requester.stdout.write("Image was squashed successfully.\n")
    if in_use:
        store.trigger_update_image_mounts()
        return "OK_BUT_REBOOT_NODES"
    return "OK"
