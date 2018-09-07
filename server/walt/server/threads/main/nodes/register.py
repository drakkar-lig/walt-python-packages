from walt.server.threads.main.network import tftp

def associate_node_image(db, mac, image_fullname, **kwargs):
    # update table node
    db.update('nodes', 'mac', mac=mac, image=image_fullname)
    db.commit()

def finalize_registration(images, db, dhcpd, **kwargs):
    # mount needed images
    images.update_image_mounts()
    # refresh the dhcpd and tftp conf
    tftp.update(db)
    dhcpd.update()

def update_images_and_finalize(images, image_fullname, **kwargs):
    images.set_image_ready(image_fullname)
    # we are all done
    finalize_registration(images = images, **kwargs)

def handle_registration_request(
                db, blocking, mac, images, model, \
                **kwargs):
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
        def callback(res):
            update_images_and_finalize(**full_kwargs)
        blocking.pull_image(image_fullname, callback)
    else:
        finalize_registration(**full_kwargs)

