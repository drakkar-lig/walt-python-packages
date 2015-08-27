from docker import Client
from plumbum.cmd import mount, umount, findmnt
from network import nfs
from network.tools import get_server_ip
from walt.server.tools import columnate
from walt.common.tools import \
        failsafe_makedirs, failsafe_symlink, succeeds
from walt.server import const
import os, re, sys, requests, uuid, shlex, time
from datetime import datetime

# Terminology:
#
# - on the server side source code:
#   we follow the *docker terminology*
#
#   <user>/<repository>:<tag>
#   <-- name --------->
#   <-- fullname ----------->
#
#   note: all walt images have <repository>='walt-node',
#   which allows to find them.
#
# - on the client side source code:
#   we follow the *walt user point of view*
#   the 'name' of an image is actually the docker <tag> only.

IMAGE_IS_USED_BUT_NOT_FOUND=\
    "WARNING: image %s is not found. Cannot attach it to related nodes.\n"
IMAGE_MOUNT_PATH='/var/lib/walt/images/%s/fs'
CONFIG_ITEM_DEFAULT_IMAGE='default_image'
SERVER_PUBKEY_PATH = '/root/.ssh/id_dsa.pub'
HOSTS_FILE_CONTENT="""\
127.0.0.1   localhost
::1     localhost ip6-localhost ip6-loopback
ff02::1     ip6-allnodes
ff02::2     ip6-allrouters
"""
MSG_BAD_NAME_SAME_AND_NOT_OWNER="""\
Bad name: Choosing the same name is only allowed if you own
the image, because it would cause the image to be overwritten.
And you do not own this image.
"""

def get_mount_path(image_fullname):
    return IMAGE_MOUNT_PATH % \
            re.sub('[^a-zA-Z0-9/-]+', '_', re.sub(':', '/', image_fullname))

def get_server_pubkey():
    with open(SERVER_PUBKEY_PATH, 'r') as f:
        return f.read()

def parse_image_fullname(image_fullname):
    image_name, image_tag = image_fullname.split(':')
    image_user, dummy = image_name.split('/')
    return image_fullname, image_name, image_user, image_tag

class ModifySession(object):
    NAME_OK             = 0
    NAME_NOT_OK         = 1
    NAME_NEEDS_CONFIRM  = 2
    exposed_NAME_OK             = NAME_OK
    exposed_NAME_NOT_OK         = NAME_NOT_OK
    exposed_NAME_NEEDS_CONFIRM  = NAME_NEEDS_CONFIRM
    def __init__(self, requester, image_fullname, repo):
        self.requester = requester
        self.image_fullname, dummy1, dummy2, self.image_tag = \
            parse_image_fullname(image_fullname)
        self.new_image_tag = None
        self.repo = repo
        self.container_name = str(uuid.uuid4())
        self.repo.register_modify_session(self)
        # expose methods to the RPyC client
        self.exposed___enter__ = self.__enter__
        self.exposed___exit__ = self.__exit__
        self.exposed_get_parameters = self.get_parameters
        self.exposed_get_default_new_name = self.get_default_new_name
        self.exposed_validate_new_name = self.validate_new_name
        self.exposed_select_new_name = self.select_new_name
    def __enter__(self):
        return self
    def __exit__(self, type, value, traceback):
        self.repo.finalize_modify(self)
    def get_parameters(self):
        # return an immutable object (a tuple, not a dict)
        # otherwise we will cause other RPyC calls
        return self.image_fullname, self.container_name
    def get_default_new_name(self):
        return self.repo.get_default_new_image_tag(
            self.requester,
            self.image_tag
        )
    def validate_new_name(self, new_image_tag):
        return self.repo.validate_new_image_tag(
            self.requester,
            self.image_tag,
            new_image_tag
        )
    def select_new_name(self, new_image_tag):
        self.new_image_tag = new_image_tag

class NodeImage(object):
    server_pubkey = get_server_pubkey()
    REMOTE = 0
    LOCAL = 1
    def __init__(self, c, fullname, state):
        self.c = c
        self.rename(fullname)
        self.set_created_at()
        self.state = state
        self.cid = None
        self.mount_path = None
        self.mounted = False
        self.server_ip = get_server_ip()
    def rename(self, fullname):
        self.fullname, self.name, self.user, self.tag = \
            parse_image_fullname(fullname)
    def set_created_at(self):
        # created_at is only available on local images
        # (downloaded or created locally)
        self.created_at = None
        for i in self.c.images():
            if self.fullname in i['RepoTags']:
                self.created_at = datetime.fromtimestamp(i['Created'])
    def __del__(self):
        if self.mounted:
            self.unmount()
    def download(self):
        for idx, line in enumerate(
                    self.c.pull(
                        self.name,
                        tag=requests.utils.quote(self.tag),
                        stream=True)):
            progress = "-/|\\"[idx % 4]
            sys.stdout.write('Downloading image %s... %s\r' % \
                                (self.fullname, progress))
            sys.stdout.flush()
        sys.stdout.write('\n')
        self.state = NodeImage.LOCAL
    def get_mount_path(self):
        return get_mount_path(self.fullname)
    def docker_command_split(self, cmd):
        args = shlex.split(cmd)
        return dict(
            entrypoint=args[0],
            command=args[1:]
        )
    def mount(self):
        print 'Mounting %s...' % self.fullname,
        self.mount_path = self.get_mount_path()
        failsafe_makedirs(self.mount_path)
        if self.state == NodeImage.REMOTE:
            self.download()
        params = dict(image=self.fullname)
        params.update(self.docker_command_split(
            'walt-node-install %s "%s"' % \
                    (self.server_ip, NodeImage.server_pubkey)))
        self.cid = self.c.create_container(**params).get('Id')
        self.c.start(container=self.cid)
        self.bind_mount()
        self.create_hosts_file()
        self.mounted = True
        print 'done'
    def unmount(self):
        print 'Un-mounting %s...' % self.fullname,
        while not succeeds('umount %s 2>/dev/null' % self.mount_path):
            time.sleep(0.1)
        self.c.kill(container=self.cid)
        self.c.wait(container=self.cid)
        self.c.remove_container(container=self.cid)
        os.rmdir(self.mount_path)
        self.mounted = False
        print 'done'
    def create_hosts_file(self):
        # since file /etc/hosts is managed by docker,
        # it appears empty on the bind mount.
        # let's create it appropriately.
        with open(self.mount_path + '/etc/hosts', 'w') as f:
            f.write(HOSTS_FILE_CONTENT)
    def list_mountpoints(self):
        return findmnt('-nlo', 'TARGET').splitlines()
    def get_mount_point(self):
        return [ line for line in self.list_mountpoints() \
                        if line.find(self.cid) != -1 ][0]
    def bind_mount(self):
        mount('-o', 'bind', self.get_mount_point(), self.mount_path)

class NodeImageRepository(object):
    def __init__(self, db):
        self.db = db
        self.c = Client(base_url='unix://var/run/docker.sock', version='auto')
        self.images = {}
        self.modify_sessions = set()
        self.add_local_images()
        self.add_remote_images()
    def add_local_images(self):
        local_images = sum([ i['RepoTags'] for i in self.c.images() ], [])
        for fullname in local_images:
            if '/walt-node' in fullname:
                self.images[fullname] = NodeImage(self.c, fullname, NodeImage.LOCAL)
    def lookup_remote_tags(self, image_name):
        url = const.DOCKER_HUB_GET_TAGS_URL % dict(image_name = image_name)
        r = requests.get(url)
        for elem in requests.get(url).json():
            tag = requests.utils.unquote(elem['name'])
            yield "%s:%s" % (image_name, tag)
    def add_remote_images(self):
        current_names = set(self.images.keys())
        remote_names = set([])
        for result in self.c.search(term='walt-node'):
            if '/walt-node' in result['name']:
                for fullname in self.lookup_remote_tags(result['name']):
                    remote_names.add(fullname)
        for fullname in (remote_names - current_names):
            self.images[fullname] = NodeImage(self.c, fullname, NodeImage.REMOTE)
    def __getitem__(self, image_fullname):
        return self.images[image_fullname]
    def __iter__(self):
        return self.images.iterkeys()
    def update_image_mounts(self, images_in_use = None):
        if images_in_use == None:
            images_in_use = self.get_images_in_use()
        images_found = []
        # ensure all needed images are mounted
        for fullname in images_in_use:
            if fullname in self.images:
                img = self.images[fullname]
                if not img.mounted:
                    img.mount()
                images_found.append(img)
            else:
                sys.stderr.write(IMAGE_IS_USED_BUT_NOT_FOUND % fullname)
        # update default image link
        self.update_default_link()
        # update nfs configuration
        nfs.update_exported_filesystems(images_found)
        # unmount images that are not needed anymore
        for fullname in self.images:
            if fullname not in images_in_use:
                img = self.images[fullname]
                if img.mounted:
                    img.unmount()
    def cleanup(self):
        # give up modify sessions
        for session in self.modify_sessions.copy():
            self.cleanup_modify_session(session)
        # release nfs mounts
        nfs.update_exported_filesystems([])
        # unmount images
        for fullname in self.images:
            img = self.images[fullname]
            if img.mounted:
                img.unmount()
    def get_images_in_use(self):
        res = set([ item.image for item in \
            self.db.execute("""
                SELECT DISTINCT image FROM nodes""").fetchall()])
        res.add(self.get_default_image())
        return res
    def get_default_image(self):
        if len(self.images) > 0:
            default_if_not_specified = self.images.keys()[0]
        else:
            default_if_not_specified = None
        return self.db.get_config(
                    CONFIG_ITEM_DEFAULT_IMAGE,
                    default_if_not_specified)
    def update_default_link(self):
        default_image = self.get_default_image()
        default_mount_path = get_mount_path(default_image)
        default_simlink = get_mount_path('default')
        failsafe_makedirs(default_mount_path)
        failsafe_symlink(default_mount_path, default_simlink)
    def get_image_from_tag(self, image_tag, requester = None):
        for image in self.images.values():
            if image.tag == image_tag:
                return image
        if requester:
            requester.stderr.write(
                "No such image '%s'. (tip: walt image show)\n" % image_tag)
        return None
    def has_image(self, requester, image_tag):
        return self.get_image_from_tag(image_tag, requester) != None
    def set_image(self, requester, node_mac, image_tag):
        image = self.get_image_from_tag(image_tag, requester)
        if image:
            self.db.update('nodes', 'mac',
                    mac=node_mac,
                    image=image.fullname)
            self.update_image_mounts()
            self.db.commit()
    def describe(self, users):
        tabular_data = []
        header = [ 'Name', 'User', 'Mounted', 'Default', 'Created' ]
        default_image_fullname = self.get_default_image()
        missing_created_at = False
        for fullname, image in self.images.iteritems():
            if image.user not in users:
                continue
            created_at = image.created_at
            if not created_at:
                created_at = 'N/A (1)'
                missing_created_at = True
            tabular_data.append([
                        image.tag,
                        image.user,
                        str(image.mounted),
                        '*' if fullname == default_image_fullname else '',
                        created_at])
        res = columnate(tabular_data, header)
        if missing_created_at:
            res += '\n\n(1): no info about creation date for remote images.'
        return res
    def set_default(self, requester, image_tag):
        image = self.get_image_from_tag(image_tag, requester)
        if image:
            self.db.set_config(
                    CONFIG_ITEM_DEFAULT_IMAGE,
                    image.fullname)
            self.update_image_mounts()
            self.db.commit()
    def create_modify_session(self, requester, image_tag):
        image = self.get_image_from_tag(image_tag, requester)
        if not image:
            requester.stderr.write('No such image.\n')
            return None
        else:
            return ModifySession(requester, image.fullname, self)
    def get_default_new_image_tag(self, requester, old_image_tag):
        image = self.get_image_from_tag(old_image_tag)
        if image.user == requester.username:
            # we can override the image, since we own it
            # => propose the same name
            return old_image_tag
        else:
            # we cannot override the image, since we do not own it
            # => propose another name
            new_tag = old_image_tag
            while self.get_image_from_tag(new_tag):
                new_tag += '_new'
            return new_tag
    def validate_new_image_tag(self, requester, old_image_tag, new_image_tag):
        existing_image = self.get_image_from_tag(new_image_tag)
        if old_image_tag == new_image_tag:
            # same name for the modified image.
            if existing_image.user != requester.username:
                requester.stderr.write(MSG_BAD_NAME_SAME_AND_NOT_OWNER)
                return ModifySession.NAME_NOT_OK
            # since the user owns the image, he is allowed to overwrite it with the modified one.
            # however, we will let the user confirm this.
            num_nodes = len(self.db.select("nodes", image=existing_image.fullname))
            reboot_message = '' if num_nodes == 0 else ' (and reboot %d node(s))' % num_nodes
            requester.stderr.write('This would overwrite the existing image%s.\n' % reboot_message)
            return ModifySession.NAME_NEEDS_CONFIRM
        else:
            if existing_image:
                requester.stderr.write('Bad name: Image already exists.\n')
                return ModifySession.NAME_NOT_OK
        if not re.match('^[a-zA-Z0-9\-_]+$', new_image_tag):
            requester.stderr.write(\
                'Bad name: Only alnum, dash(-) and underscore(_) characters are allowed.\n')
            return ModifySession.NAME_NOT_OK
        return ModifySession.NAME_OK
    def register_modify_session(self, session):
        self.modify_sessions.add(session)
    def cleanup_modify_session(self, session):
        cname = session.container_name
        # kill/remove the container if it ever existed
        try:
            self.c.kill(container=cname)
        except:
            pass
        try:
            self.c.wait(container=cname)
        except:
            pass
        try:
            self.c.remove_container(container=cname)
        except:
            pass
        self.modify_sessions.remove(session)

    def umount_used_image(self, image):
        images = self.get_images_in_use()
        images.remove(image.fullname)
        self.update_image_mounts(images)

    def finalize_modify(self, session):
        requester = session.requester
        old_image_tag = session.image_tag
        new_image_tag = session.new_image_tag
        container_name = session.container_name
        if new_image_tag:
            image_name = '%s/walt-node' % requester.username
            self.c.commit(
                    container=container_name,
                    repository=image_name,
                    tag=new_image_tag,
                    message='Image modified using walt image shell')
            if old_image_tag == new_image_tag:
                # same name, we are modifying the image
                image = self.get_image_from_tag(new_image_tag)
                # if image is mounted, umount/mount it in order to make
                # the nodes reboot with the new version
                if image.mounted:
                    # umount
                    self.umount_used_image(image)
                    # re-mount
                    self.update_image_mounts()
                # done.
                requester.stdout.write('Image %s updated.\n' % new_image_tag)
            else:
                # we are saving changes to a new image, leaving the initial one
                # unchanged
                fullname = '%s:%s' % (image_name, new_image_tag)
                self.images[fullname] = NodeImage(self.c, fullname, NodeImage.LOCAL)
                requester.stdout.write('New image %s saved.\n' % new_image_tag)
        self.cleanup_modify_session(session)

    def get_local_unmounted_image_from_tag(self, image_tag, requester):
        image = self.get_image_from_tag(image_tag, requester)
        if image:   # otherwise issue is already reported
            if image.state != NodeImage.LOCAL:
                requester.stderr.write('Sorry, this operation is allowed on local images only.\n')
                return None
            if image.mounted:
                requester.stderr.write('Sorry, cannot proceed because the image is mounted.\n')
                return None
        return image

    def remove(self, requester, image_tag):
        image = self.get_local_unmounted_image_from_tag(image_tag, requester)
        if image:   # otherwise issue is already reported
            name = image.fullname
            del self.images[name]
            self.c.remove_image(
                    image=name, force=True)

    def do_rename(self, image, new_user, new_tag):
        old_fullname = image.fullname
        new_name = "%s/walt-node" % new_user
        new_fullname = "%s:%s" % (new_name, new_tag)
        # update image internal attributes
        image.rename(new_fullname)
        # rename in this repo
        self.images[new_fullname] = image
        del self.images[old_fullname]
        # rename the docker image
        self.c.tag(image=old_fullname, repository=new_name, tag=new_tag)
        self.c.remove_image(image=old_fullname, force=True)

    def rename(self, requester, image_tag, new_tag):
        image = self.get_local_unmounted_image_from_tag(image_tag, requester)
        if image:   # otherwise issue is already reported
            if self.get_image_from_tag(new_tag):
                requester.stderr.write('Bad name: Image already exists.\n')
                return
            self.do_rename(image, image.user, new_tag)

    def get_owner(self, requester, image_tag):
        image = self.get_image_from_tag(image_tag, requester)
        if image:   # otherwise issue is already reported
            return image.user

    def fix_owner(self, requester, image_tag):
        image = self.get_local_unmounted_image_from_tag(image_tag, requester)
        if image:   # otherwise issue is already reported
            self.do_rename(image, requester.username, image_tag)

