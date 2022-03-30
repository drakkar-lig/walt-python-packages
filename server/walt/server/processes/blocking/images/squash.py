from walt.server.processes.blocking.images.commit import commit_image
from walt.server.exttools import buildah
from subprocess import CalledProcessError

def squash_image(local_images, image_fullname):
    cont_name = 'squash:' + image_fullname
    try:
        buildah('from', '--pull-never', '--name', cont_name, image_fullname)
    except CalledProcessError:
        print('Note: walt server was probably not stopped properly and container still exists.')
        print('      removing container and restarting command.')
        buildah.rm(cont_name)
        buildah('from', '--pull-never', '--name', cont_name, image_fullname)
    commit_image(local_images, cont_name, image_fullname, tool=buildah, opts=('--squash',))

# this implements walt image squash
def squash(requester, server, image_fullname):
    store = server.images.store
    image = store[image_fullname]
    in_use = image.in_use()
    image.filesystem.close()
    squash_image(server.repository, image_fullname)
    requester.stdout.write('Image was squashed successfully.\n')
    if in_use:
        store.update_image_mounts()
        return 'OK_BUT_REBOOT_NODES'
    return 'OK'
