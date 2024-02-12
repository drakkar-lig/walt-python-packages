import sys

from walt.server.processes.main.workflow import Workflow


def decapitalize(msg):
    return msg[0].lower() + msg[1:]


def handle_registration_request(
    db, logs, blocking, exports, mac, images, model, image_fullname=None, **kwargs
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
        logs.platform_log("devices",
            f"Device {db_info.name} pretends to be a walt node of type '{model}'.")
        logs.platform_log("devices",
            (
                f"Trying to download a default image for '{model}' nodes:"
                f" {image_fullname}..."
            ))
        wf_steps += [wf_pull_image, wf_after_pull_image]
    wf_steps += [wf_update_device_in_db, exports.wf_update_persist_exports,
                 images.wf_update_image_mounts, wf_dhcpd_named_update]
    wf = Workflow(wf_steps, **full_kwargs)
    wf.run()


def wf_pull_image(wf, blocking, image_fullname, **env):
    blocking.pull_image(None, image_fullname, wf.next)


def wf_after_pull_image(wf, pull_result, image_fullname, model, logs, **env):
    if pull_result[0]:
        # ok
        logs.platform_log("devices",
            f"Image {image_fullname} was downloaded successfully.")
        wf.next()
    else:
        failure = pull_result[1]
        # not being able to download default images for nodes
        # is a rather important issue
        logs.platform_log("devices", decapitalize(failure), error=True)
        logs.platform_log("devices",
            (
                f"New {model} nodes will be seen as devices of type 'unknown' until"
                " this is solved."
            ), error=True)


def wf_update_device_in_db(wf, devices, mac, model, image_fullname, **env):
    # turn the device into a node
    devices.add_or_update(mac=mac, type="node", model=model, image=image_fullname)
    wf.next()


def wf_dhcpd_named_update(wf, dhcpd, named, **env):
    # refresh the dhcpd and named (DNS) conf
    dhcpd.update()
    named.update()
    wf.next()
