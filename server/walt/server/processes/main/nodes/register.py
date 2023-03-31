from walt.server.processes.main.network import tftp
import sys

def finalize_registration(devices, images, db, dhcpd, mac, image_fullname, model, **kwargs):
    # turn the device into a node
    devices.add_or_update(mac = mac, type = 'node', model = model, image = image_fullname)
    # mount needed images
    images.update_image_mounts()
    # refresh the dhcpd and tftp conf
    tftp.update(db, images)
    dhcpd.update()

def decapitalize(msg):
    return msg[0].lower() + msg[1:]

def dup_msg(msg, stdstream, logs):
    stdstream.write(msg + '\n')
    logs.platform_log('devices', decapitalize(msg))

def pull_image(blocking, images, image_fullname, model, logs, **kwargs):
    full_kwargs = dict(
        images = images,
        image_fullname = image_fullname,
        model = model,
        logs = logs,
        **kwargs
    )
    def callback(pull_result):
        if pull_result[0]:
            # ok
            images.register_image(image_fullname)
            dup_msg(f"Image {image_fullname} was downloaded successfully.", sys.stdout, logs)
            finalize_registration(**full_kwargs)
        else:
            failure = pull_result[1]
            # not being able to download default images for nodes
            # is a rather important issue
            dup_msg(failure, sys.stderr, logs)
            dup_msg(f"New {model} nodes will be seen as devices of type 'unknown' until this is solved.",
                    sys.stderr, logs)
    blocking.pull_image(image_fullname, callback)

def handle_registration_request(
                db, logs, blocking, mac, images, model, image_fullname = None,
                **kwargs):
    if image_fullname is None:
        image_fullname = images.get_default_image_fullname(model)
    # register the node
    full_kwargs = dict(
        db = db,
        images = images,
        mac = mac,
        image_fullname = image_fullname,
        model = model,
        logs = logs,
        **kwargs
    )
    # if image is new
    if image_fullname not in images:
        # we have to pull an image, that will be long,
        # let's inform the user (by logs) and do this asynchronously
        db_info = db.select_unique('devices', mac = mac)
        dup_msg(f"Device {db_info.name} pretends to be a walt node of type '{model}'.",
                sys.stdout, logs)
        dup_msg(f"Trying to download a default image for '{model}' nodes: {image_fullname}...",
                sys.stdout, logs)
        pull_image(blocking, **full_kwargs)
    else:
        finalize_registration(**full_kwargs)
