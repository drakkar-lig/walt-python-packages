import functools

from walt.common.evloop import EventLoop


def _check_retcode(verb, retcode):
    if retcode != 0:
        raise Exception(f"Failed to {verb}")


def _run_parallel_commands(cmds, verb):
    if len(cmds) > 0:
        ev_loop = EventLoop()
        cmd_check = functools.partial(_check_retcode, verb)
        for cmd in cmds:
            ev_loop.do(cmd, callback=cmd_check, silent=False)
        # the loop will run until all cmds have ended
        ev_loop.loop()


def _wf_mount_images(wf, image_mount_cmds, **env):
    _run_parallel_commands(image_mount_cmds, "mount image")
    wf.next()


def _wf_mount_nodes_rw(wf, node_rw_mount_cmds, **env):
    _run_parallel_commands(node_rw_mount_cmds, "mount node-rw layer")
    wf.next()


def _wf_umount_images(wf, image_umount_cmds, **env):
    _run_parallel_commands(image_umount_cmds, "umount image")
    wf.next()


def _wf_umount_nodes_rw(wf, node_rw_umount_cmds, **env):
    _run_parallel_commands(node_rw_umount_cmds, "umount node-rw layer")
    wf.next()


def wf_add_mounts(wf, added_mounts, **env):
    if len(added_mounts) > 0:
        image_mount_cmds = []
        node_rw_mount_cmds = []
        for mount_info in added_mounts:
            directive_verb, args = mount_info[0], mount_info[1:]
            if directive_verb == "MOUNT-IMAGE":
                image_mount_cmds.append(
                        "walt-image-mount --image " + " ".join(args))
            else:
                node_rw_mount_cmds.append(
                        "walt-image-mount --node-rw " + " ".join(args))
        wf.insert_steps([
                _wf_mount_images,
                _wf_mount_nodes_rw,
                ])
        wf.update_env(
                image_mount_cmds=image_mount_cmds,
                node_rw_mount_cmds=node_rw_mount_cmds,
        )
    wf.next()


def wf_remove_mounts(wf, removed_mounts, preserve_node_rw_data = (), **env):
    if len(removed_mounts) > 0:
        image_umount_cmds = []
        node_rw_umount_cmds = []
        for mount_info in removed_mounts:
            directive_verb, args = mount_info[0], mount_info[1:]
            if directive_verb == "MOUNT-IMAGE":
                image_id = args[0]
                image_umount_cmds.append(
                        "walt-image-umount --image " + image_id)
            else:
                cmd = "walt-image-umount --node-rw "
                if mount_info in preserve_node_rw_data:
                    cmd += "--preserve-container "
                node_rw_umount_cmds.append(cmd + " ".join(args))
        wf.insert_steps([
                _wf_umount_images,
                _wf_umount_nodes_rw,
                ])
        wf.update_env(
                image_umount_cmds=image_umount_cmds,
                node_rw_umount_cmds=node_rw_umount_cmds,
        )
    wf.next()
