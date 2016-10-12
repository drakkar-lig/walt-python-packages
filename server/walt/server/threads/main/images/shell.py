import uuid
from walt.server.threads.main.images.image import parse_image_fullname, validate_image_tag

# About terminology: See comment about it in image.py.
class ImageShellSession(object):

    def __init__(self, images, requester, image_fullname):
        self.images = images
        self.docker = images.docker
        self.requester = requester
        self.image_fullname, dummy1, dummy2, dummy3, self.image_tag = \
            parse_image_fullname(image_fullname)
        self.container_name = str(uuid.uuid4())
        self.docker_events = self.docker.events()

    def get_parameters(self):
        # return an immutable object (a tuple, not a dict)
        # otherwise we will cause other RPyC calls
        # default new name is to propose the same name
        # (and override the image if user confirms)
        return self.image_fullname, self.container_name, self.image_tag

    def save(self, new_image_tag, name_confirmed):
        username = self.requester.get_username()
        if not username:
            return None    # client already disconnected, give up
        # 1st step: validate new name
        existing_image = self.images.get_user_image_from_tag(
                                        self.requester,
                                        new_image_tag,
                                        expected=None)
        if self.image_tag == new_image_tag:
            if name_confirmed:
                pass
            else:
                # same name for the modified image.
                # this would overwrite the existing one.
                # we will let the user confirm this.
                self.images.warn_overwrite_image(self.requester, existing_image.fullname)
                return 'NAME_NEEDS_CONFIRM'
        else:   # save as a different name
            if existing_image:
                self.requester.stderr.write('Bad name: Image already exists.\n')
                return 'NAME_NOT_OK'
        # verify name syntax
        if not validate_image_tag(self.requester, new_image_tag):
            return 'NAME_NOT_OK'
        # ok, all is fine

        # 2nd step: save the image
        image_fullname = '%s/walt-node:%s' % (username, new_image_tag)
        # with the walt image cp command, the client sends a request to start a
        # container for receiving, then immediately starts to send a tar archive,
        # and then tries to commit the container through rpyc commands.
        # we have to ensure here that the container was run and completed its job.
        while True:
            event = self.docker_events.next()
            if event['status'] == 'die' and \
                    self.docker.get_container_name(event['id']) == self.container_name:
                break
        print 'committing %s...' % self.container_name
        self.docker.commit(self.container_name, image_fullname,
                'Image modified using walt image [cp|shell]')
        if self.image_tag == new_image_tag:
            # same name, we are modifying the image
            image = self.images.get_user_image_from_tag(self.requester, new_image_tag)
            # let the image know that a new layer was just commited
            image.update_top_layer_id()
            # if image is mounted, umount/mount it in order to make
            # the nodes reboot with the new version
            node_reboot_msg = ''
            if image.mounted:
                node_reboot_msg = ' (nodes using it are rebooting)'
                # umount
                self.images.umount_used_image(image)
                # re-mount
                # (just in case the user tried to update the walt-node package, since this
                # image in mounted we cannot let the user install a walt-node version
                # uncompatible with the server. auto_update = True will restore an appropriate
                # version if needed.)
                self.images.update_image_mounts(auto_update = True)
            # done.
            self.requester.stdout.write('Image %s updated%s.\n' % \
                            (new_image_tag, node_reboot_msg))
        else:
            # we are saving changes to a new image, leaving the initial one
            # unchanged
            self.images.register_image(image_fullname, True)
            self.requester.stdout.write('New image %s saved.\n' % new_image_tag)
        return 'OK_SAVED'

    def cleanup(self):
        self.docker.stop_container(self.container_name)

