from docker import Client
from plumbum.cmd import mount, umount, findmnt
from network import nfs
import os, sys

DUMMY_CMD = 'tail -f /dev/null'
IMAGE_IS_USED_BUT_NOT_FOUND=\
    "WARNING: image %s is not found. Cannot attach it to related nodes."
IMAGE_MOUNT_PATH='/var/lib/walt/images/%s/fs'

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
        if not os.path.exists(self.mount_path):
            os.makedirs(self.mount_path)
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
        return [ item['image'] for item in \
            self.db.execute("SELECT DISTINCT image FROM nodes;").fetchall() ]




