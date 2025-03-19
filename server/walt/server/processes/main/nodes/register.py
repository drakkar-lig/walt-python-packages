import sys

from walt.server.processes.main.workflow import Workflow

currently_registering_macs = set()


def decapitalize(msg):
    return msg[0].lower() + msg[1:]


def handle_registration_request(
    db, logs, exports, mac, images, model, image_fullname=None, **kwargs
):
    if mac in currently_registering_macs:
        # we already started a registration procedure for this mac,
        # ignore this one
        return
    currently_registering_macs.add(mac)
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
        **kwargs,
    )
    wf_steps = []
    # if image is new
    if image_fullname not in images:
        # we have to pull an image, that will be long,
        # let's inform the user (by logs) and do this asynchronously
        db_info = db.select_unique("devices", mac=mac)
        logs.platform_log("devices",
            line=f"Device {db_info.name} is a walt node of type '{model}'.")
        logs.platform_log("devices",
            line=(
                f"Trying to download a default image for '{model}' nodes:"
                f" {image_fullname}..."
            ))
        wf_steps += [wf_pull_image, wf_after_pull_image]
    wf_steps += [wf_update_device_in_db, wf_update_status_manager,
                 exports.wf_update_persist_exports,
                 images.wf_update_image_mounts, wf_dhcpd_named_update,
                 wf_done_registering_mac]
    wf = Workflow(wf_steps, **full_kwargs)
    wf.run()


def wf_pull_image(wf, blocking, image_fullname, **env):
    blocking.pull_image(None, image_fullname, wf.next)


def wf_after_pull_image(wf, pull_result, image_fullname, mac, model, logs, **env):
    if pull_result[0]:
        # ok
        logs.platform_log("devices",
            line=f"Image {image_fullname} was downloaded successfully.")
        wf.next()
    else:
        failure = pull_result[1]
        # not being able to download default images for nodes
        # is a rather important issue
        logs.platform_log("devices", line=decapitalize(failure), error=True)
        logs.platform_log("devices",
            line=(
                f"New {model} nodes will be seen as devices of type 'unknown' until"
                " this is solved."
            ), error=True)
        currently_registering_macs.discard(mac)
        wf.interrupt()


def wf_update_device_in_db(wf, devices, mac, model, image_fullname, **env):
    # turn the device into a node
    devices.add_or_update(mac=mac, type="node", model=model, image=image_fullname)
    wf.next()

def wf_update_status_manager(wf, status_manager, mac, **env):
    status_manager.register_node(mac)
    wf.next()

def wf_dhcpd_named_update(wf, dhcpd, named, **env):
    # refresh the dhcpd and named (DNS) conf
    dhcpd.update()
    named.update()
    wf.next()

def wf_done_registering_mac(wf, mac, **env):
    currently_registering_macs.discard(mac)
    wf.next()
