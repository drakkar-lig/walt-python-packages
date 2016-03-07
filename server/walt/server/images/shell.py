import uuid, time
from walt.server.images.image import parse_image_fullname, validate_image_tag

# About terminology: See comment about it in image.py.
class ImageShellSessionStore(object):
    def __init__(self, docker, images):
        self.docker = docker
        self.images = images
        self.sessions = set()
    def create_session(self, requester, image_tag):
        image = self.images.get_user_image_from_tag(requester, image_tag)
        if image:
            session = ImageShellSession(self, self.images,
                                    requester, image.fullname)
            self.sessions.add(session)
            return session
    def cleanup_session(self, session):
        session.cleanup()
        self.sessions.remove(session)
    def cleanup(self):
        for session in self.sessions:
            session.cleanup()
        self.sessions = {}

class ImageShellSession(object):
    NAME_OK             = 0
    NAME_NOT_OK         = 1
    NAME_NEEDS_CONFIRM  = 2
    exposed_NAME_OK             = NAME_OK
    exposed_NAME_NOT_OK         = NAME_NOT_OK
    exposed_NAME_NEEDS_CONFIRM  = NAME_NEEDS_CONFIRM
    def __init__(self, store, images, requester, image_fullname):
        self.store = store
        self.docker = store.docker
        self.images = images
        self.requester = requester
        self.image_fullname, dummy1, dummy2, dummy3, self.image_tag = \
            parse_image_fullname(image_fullname)
        self.new_image_tag = None
        self.container_name = str(uuid.uuid4())
        self.docker_events = self.docker.events()
        # expose methods to the RPyC client
        self.exposed___enter__ = self.__enter__
        self.exposed___exit__ = self.__exit__
        self.exposed_get_parameters = self.get_parameters
        self.exposed_get_default_new_name = self.get_default_new_name
        self.exposed_validate_new_name = self.validate_new_image_tag
        self.exposed_select_new_name = self.select_new_name
    def __enter__(self):
        return self
    def __exit__(self, type, value, traceback):
        self.finalize()
    def get_parameters(self):
        # return an immutable object (a tuple, not a dict)
        # otherwise we will cause other RPyC calls
        return self.image_fullname, self.container_name
    def get_default_new_name(self):
        # default is to propose the same name
        # (and override the image if user confirms)
        return self.image_tag
    def select_new_name(self, new_image_tag):
        self.new_image_tag = new_image_tag
    def validate_new_image_tag(self, new_image_tag):
        existing_image = self.images.get_user_image_from_tag(
                                        self.requester,
                                        new_image_tag,
                                        expected=None)
        if self.image_tag == new_image_tag:
            # same name for the modified image.
            # this would overwrite the existing one.
            # we will let the user confirm this.
            self.images.warn_overwrite_image(self.requester, existing_image.fullname)
            return ImageShellSession.NAME_NEEDS_CONFIRM
        else:
            if existing_image:
                self.requester.stderr.write('Bad name: Image already exists.\n')
                return ImageShellSession.NAME_NOT_OK
        if not validate_image_tag(self.requester, new_image_tag):
            return ImageShellSession.NAME_NOT_OK
        return ImageShellSession.NAME_OK
    def finalize(self):
        if self.new_image_tag:
            image_fullname = '%s/walt-node:%s' % (
                    self.requester.username, self.new_image_tag)
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
            if self.image_tag == self.new_image_tag:
                # same name, we are modifying the image
                image = self.images.get_user_image_from_tag(self.requester, self.new_image_tag)
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
                    self.images.update_image_mounts()
                # done.
                self.requester.stdout.write('Image %s updated%s.\n' % \
                                (self.new_image_tag, node_reboot_msg))
            else:
                # we are saving changes to a new image, leaving the initial one
                # unchanged
                self.images.register_image(image_fullname, True)
                self.requester.stdout.write('New image %s saved.\n' % self.new_image_tag)
        self.store.cleanup_session(self)
    def cleanup(self):
        self.docker.stop_container(self.container_name)

