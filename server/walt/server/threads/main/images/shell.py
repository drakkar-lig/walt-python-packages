import uuid
from walt.server.threads.main.images.image import validate_image_name, format_image_fullname

# About terminology: See comment about it in image.py.
class ImageShellSession(object):

    def __init__(self, images, image, task_label):
        self.images = images
        self.docker = images.docker
        self.image = image
        self.container_name = str(uuid.uuid4())
        self.docker_events = self.docker.local.events()
        self.image.task_label = task_label

    def get_parameters(self):
        # return an immutable object (a tuple, not a dict)
        # otherwise we will cause other RPC calls
        # default new name is to propose the same name
        # (and override the image if user confirms)
        return self.image.fullname, self.container_name, self.image.name

    def save(self, requester, new_image_name, name_confirmed):
        username = requester.get_username()
        if not username:
            return 'GIVE_UP'    # client already disconnected, give up
        # 1st step: validate new name
        existing_image = self.images.get_user_image_from_name(
                                        requester,
                                        new_image_name,
                                        expected=None)
        if self.image.name == new_image_name:
            if name_confirmed:
                pass
            else:
                # same name for the modified image.
                # this would overwrite the existing one.
                # we will let the user confirm this.
                self.images.warn_overwrite_image(requester, self.image.name)
                return 'NAME_NEEDS_CONFIRM'
        else:   # save as a different name
            if existing_image:
                requester.stderr.write('Bad name: Image already exists.\n')
                return 'NAME_NOT_OK'
        # verify name syntax
        if not validate_image_name(requester, new_image_name):
            return 'NAME_NOT_OK'
        # ok, all is fine

        # 2nd step: save the image
        image_fullname = format_image_fullname(username, new_image_name)
        # with the walt image cp command, the client sends a request to start a
        # container for receiving, then immediately starts to send a tar archive,
        # and then tries to commit the container through rpc commands.
        # we have to ensure here that the container was run and completed its job.
        while True:
            event = self.docker_events.next()
            if 'status' not in event:
                continue
            if event['status'] == 'die' and \
                    self.docker.local.get_container_name(event['id']) == self.container_name:
                break
        print 'committing %s...' % self.container_name
        self.docker.local.commit(self.container_name, image_fullname,
                'Image modified using walt image [cp|shell]')
        if self.image.fullname == image_fullname:
            # same name, we are modifying the image
            # if image is mounted, umount/mount it in order to make changes
            # available to nodes
            if self.image.mounted:
                # umount
                self.images.umount_used_image(self.image)
                # re-mount
                self.images.update_image_mounts()
            # done.
            requester.stdout.write('Image %s updated.\n' % new_image_name)
            self.image.task_label = None
            return 'OK_BUT_REBOOT_NODES'
        else:
            # we are saving changes to a new image, leaving the initial one
            # unchanged
            self.images.register_image(image_fullname, True)
            requester.stdout.write('New image %s saved.\n' % new_image_name)
            self.image.task_label = None
            return 'OK_SAVED'

    def cleanup(self):
        self.docker.local.stop_container(self.container_name)
        self.image.task_label = None

