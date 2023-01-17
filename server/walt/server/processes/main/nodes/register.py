from walt.server.processes.main.network import tftp
import sys

def associate_node_image(db, mac, image_fullname, **kwargs):
    # update table node
    db.update('nodes', 'mac', mac=mac, image=image_fullname)
    db.commit()

def finalize_registration(images, db, dhcpd, **kwargs):
    # mount needed images
    images.update_image_mounts()
    # refresh the dhcpd and tftp conf
    tftp.update(db, images)
    dhcpd.update()

def update_images_and_finalize(images, image_fullname, **kwargs):
    images[image_fullname].ready = True
    # we are all done
    finalize_registration(images = images, **kwargs)

def dup_error(msg, logs, **kwargs):
    sys.stderr.write(msg + '\n')
    logs.platform_log('devices', msg)

def pull_image(blocking, image_fullname, **kwargs):
    full_kwargs = dict(
        image_fullname = image_fullname,
        **kwargs
    )
    def callback(pull_result):
        if pull_result[0]:
            # ok
            update_images_and_finalize(**full_kwargs)
        else:
            failure = pull_result[1]
            # not being able to download default images for nodes
            # is a rather critical issue!
            dup_error(failure, **full_kwargs)
            dup_error("CANNOT FULFILL NODE REGISTRATION!!", **full_kwargs)
    blocking.pull_image(image_fullname, callback)

def handle_registration_request(
                db, blocking, mac, images, model, image_fullname = None,
                **kwargs):
    if image_fullname is None:
        image_fullname = images.get_default_image_fullname(model)
    image_is_new = image_fullname not in images
    # if image is new, register it before the node
    # (cf db integrity constraint)
    if image_is_new:
        images.register_image(image_fullname, False)
    # register the node
    full_kwargs = dict(
        db = db,
        images = images,
        mac = mac,
        image_fullname = image_fullname,
        **kwargs
    )
    associate_node_image(**full_kwargs)
    # if image is new
    if image_is_new:
        # we have to pull an image, that will be long,
        # let's do this asynchronously
        pull_image(blocking, **full_kwargs)
    else:
        finalize_registration(**full_kwargs)

def restore_interrupted_registration(**kwargs):
    pull_image(**kwargs)
