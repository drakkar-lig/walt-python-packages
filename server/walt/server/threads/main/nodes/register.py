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

class AsyncPullTask(object):
    def __init__(self, docker, image_fullname, finalize_cb, finalize_cb_kwargs):
        self.docker = docker
        self.image_fullname = image_fullname
        self.finalize_cb = finalize_cb
        self.finalize_cb_kwargs = finalize_cb_kwargs
    def perform(self):
        # pull image: this is where things may take some time...
        self.docker.pull(self.image_fullname)
    def handle_result(self, res):
        # this should go fast
        self.finalize_cb(**self.finalize_cb_kwargs)

def handle_registration_request(
                db, docker, blocking, mac, images, model, \
                **kwargs):
    image_fullname = images.get_default_image(model)
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
        blocking.do(AsyncPullTask(docker, image_fullname,
                            update_images_and_finalize, full_kwargs))
    else:
        finalize_registration(**full_kwargs)

