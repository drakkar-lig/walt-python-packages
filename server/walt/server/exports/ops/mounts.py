
def _wf_check_retcode(wf, verb, retcode, **env):
    if retcode != 0:
        raise Exception(f"Failed to {verb} an image")
    wf.next()


def _wf_unmount(self, wf, image_id, deadlines, ev_loop, **env):
    deadlines.pop(image_id, None)
    ev_loop.do(
            f"walt-image-umount {image_id}",
            functools.partial(_wf_check_retcode, wf, "umount"),
            silent=False)


def _wf_unmount_images(self, wf, image_ids_pending_unmount, **env):
    if len(image_ids_pending_unmount) > 0:
        steps = []
        for image_id in image_ids_pending_unmount:
            step = functools.partial(_wf_unmount, image_id=image_id)
            steps.append(step)
        wf.insert_parallel_steps(steps)
    wf.next()


def wf_mount_images(wf, image_mounts, **env):

