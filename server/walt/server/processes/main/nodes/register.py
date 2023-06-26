import sys

from walt.server.processes.main.workflow import Workflow


def decapitalize(msg):
    return msg[0].lower() + msg[1:]


def dup_msg(msg, stdstream, logs):
    stdstream.write(msg + "\n")
    logs.platform_log("devices", decapitalize(msg))


def handle_registration_request(
    db, logs, blocking, mac, images, model, image_fullname=None, **kwargs
):
    if image_fullname is None:
        image_fullname = images.get_default_image_fullname(model)
    # register the node
    full_kwargs = dict(
        db=db,
        images=images,
        mac=mac,
        image_fullname=image_fullname,
        model=model,
        logs=logs,
        blocking=blocking,
        **kwargs,
    )
    wf_steps = []
    # if image is new
    if image_fullname not in images:
        # we have to pull an image, that will be long,
        # let's inform the user (by logs) and do this asynchronously
        db_info = db.select_unique("devices", mac=mac)
        dup_msg(
            f"Device {db_info.name} pretends to be a walt node of type '{model}'.",
            sys.stdout,
            logs,
        )
        dup_msg(
            (
                f"Trying to download a default image for '{model}' nodes:"
                f" {image_fullname}..."
            ),
            sys.stdout,
            logs,
        )
        wf_steps += [wf_pull_image, wf_after_pull_image]
    wf_steps += [wf_update_device_in_db, images.wf_update_image_mounts, wf_dhcpd_update]
    wf = Workflow(wf_steps, **full_kwargs)
    wf.run()


def wf_pull_image(wf, blocking, image_fullname, **env):
    blocking.pull_image(None, image_fullname, wf.next)


def wf_after_pull_image(wf, pull_result, image_fullname, model, logs, **env):
    if pull_result[0]:
        # ok
        dup_msg(
            f"Image {image_fullname} was downloaded successfully.", sys.stdout, logs
        )
        wf.next()
    else:
        failure = pull_result[1]
        # not being able to download default images for nodes
        # is a rather important issue
        dup_msg(failure, sys.stderr, logs)
        dup_msg(
            (
                f"New {model} nodes will be seen as devices of type 'unknown' until"
                " this is solved."
            ),
            sys.stderr,
            logs,
        )


def wf_update_device_in_db(wf, devices, mac, model, image_fullname, **env):
    # turn the device into a node
    devices.add_or_update(mac=mac, type="node", model=model, image=image_fullname)
    wf.next()


def wf_dhcpd_update(wf, dhcpd, **env):
    # refresh the dhcpd conf
    dhcpd.update()
    wf.next()
