from docker import Client
from plumbum.cmd import mount, umount, findmnt
from network import nfs
from walt.server.tools import \
        failsafe_makedirs, failsafe_symlink, columnate
import os, sys

DUMMY_CMD = 'tail -f /dev/null'
IMAGE_IS_USED_BUT_NOT_FOUND=\
    "WARNING: image %s is not found. Cannot attach it to related nodes.\n"
IMAGE_MOUNT_PATH='/var/lib/walt/images/%s/fs'
CONFIG_ITEM_DEFAULT_IMAGE='default_image'

def get_mount_path(image_name):
    return IMAGE_MOUNT_PATH % image_name

class NodeImage(object):
    REMOTE = 0
    LOCAL = 1
    def __init__(self, c, name, state):
        self.c = c
        self.name = name
        self.state = state
        self.cid = None
        self.mount_path = None
        self.mounted = False
    def __del__(self):
        if self.mounted:
            self.unmount()
    def download(self):
        for idx, line in enumerate(self.c.pull(self.name, stream=True)):
            progress = "-/|\\"[idx % 4]
            sys.stdout.write('Downloading image %s... %s\r' % \
                                (self.name, progress))
            sys.stdout.flush()
        sys.stdout.write('\n')
        self.state = NodeImage.LOCAL
    def mount(self):
        print 'Mounting %s...' % self.name,
        self.mount_path = get_mount_path(self.name)
        failsafe_makedirs(self.mount_path)
        if self.state == NodeImage.REMOTE:
            self.download()
        self.cid = self.c.create_container(             \
                            image=self.name,            \
                            command=DUMMY_CMD).get('Id')
        self.c.start(container=self.cid)
        self.bind_mount()
        self.mounted = True
        print 'done'
    def unmount(self):
        print 'Un-mounting %s...' % self.name,
        umount('-lf', self.mount_path)
        self.c.kill(container=self.cid)
        self.c.wait(container=self.cid)
        self.c.remove_container(container=self.cid)
        os.rmdir(self.mount_path)
        self.mounted = False
        print 'done'
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
        local_images = sum([ i['RepoTags'] for i in self.c.images() ], [])
        local_images = set([ name.split(':')[0] for name in local_images ])
        self.images = {
            name: NodeImage(self.c, name, NodeImage.LOCAL) \
                for name in local_images }
        self.add_remote_images()
    def add_remote_images(self):
        current_names = set(self.images.keys())
        remote_names = set([ result['name'] \
                for result in self.c.search(term='waltplatform') \
                if result['name'].startswith('waltplatform/rpi') ])
        for name in (remote_names - current_names):
            self.images[name] = NodeImage(self.c, name, NodeImage.REMOTE)
    def __getitem__(self, key):
        return self.images[key]
    def __iter__(self):
        return self.images.iterkeys()
    def update_image_mounts(self):
        images_in_use = self.get_images_in_use()
        images_found = []
        # ensure all needed images are mounted
        for name in images_in_use:
            if name in self.images:
                img = self.images[name]
                if not img.mounted:
                    img.mount()
                images_found.append(img)
            else:
                sys.stderr.write(IMAGE_IS_USED_BUT_NOT_FOUND % name)
        # unmount images that are not needed anymore
        for name in self.images:
            if name not in images_in_use:
                img = self.images[name]
                if img.mounted:
                    img.unmount()
        # update default image link
        self.update_default_link()
        # update nfs configuration
        nfs.update_exported_filesystems(images_found)
    def cleanup(self):
        # release nfs mounts
        nfs.update_exported_filesystems([])
        # unmount images
        for name in self.images:
            img = self.images[name]
            if img.mounted:
                img.unmount()
    def get_images_in_use(self):
        res = set([ item['image'] for item in \
            self.db.execute("""
                SELECT DISTINCT image FROM nodes""").fetchall()])
        res.add(self.get_default_image())
        print res
        sys.stdout.flush()
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
    def check_image_exists(self, requester, image_name):
        if not image_name in self:
            requester.write_stderr(
                "No such image '%s'. (tip: walt image list)\n" % image_name)
            return False
        return True
    def set_image(self, requester, node_mac, image_name):
        if self.check_image_exists(requester, image_name):
            self.db.update('nodes', 'mac', mac=node_mac, image=image_name)
            self.update_image_mounts()
            self.db.commit()
    def describe(self):
        tabular_data = []
        header = [ 'Name', 'State', 'Mounted', 'Default' ]
        state_labels = {
                NodeImage.REMOTE: 'Remote',
                NodeImage.LOCAL: 'Local'
        }
        default = self.get_default_image()
        for name, image in self.images.iteritems():
            tabular_data.append([
                        name,
                        state_labels[image.state],
                        str(image.mounted),
                        '*' if name == default else ''])
        return columnate(tabular_data, header)
    def set_default(self, requester, image_name):
        if self.check_image_exists(requester, image_name):
            self.db.set_config(
                    CONFIG_ITEM_DEFAULT_IMAGE,
                    image_name)
            self.update_image_mounts()
            self.db.commit()

