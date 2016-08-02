
MSG_WOULD_REBOOT_NODES="""\
This image is in use. This operation would cause %d nodes to reboot.
Re-run with option --force if this is what you want.
"""

def update_walt_software(images, requester, image_tag, force):
    image = images.get_user_image_from_tag(requester, image_tag)
    if image:   # otherwise issue is already reported
        num_nodes = images.num_nodes_using_image(image.fullname)
        if num_nodes > 0 and not force:
            requester.stderr.write(MSG_WOULD_REBOOT_NODES % num_nodes)
            return
        need_umount_mount = image.mounted
        if need_umount_mount:
            # unmount
            images.umount_used_image(image)
        image.update_walt_software()
        if need_umount_mount:
            # re-mount
            images.update_image_mounts()

