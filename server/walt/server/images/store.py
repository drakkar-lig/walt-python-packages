from walt.server.images.image import NodeImage
# About terminology: See comment about it in image.py.

class NodeImageStore(object):
    def __init__(self, c):
        self.c = c
        self.images = {}
    def refresh(self):
        local_images = sum([ i['RepoTags'] for i in self.c.images() ], [])
        # add missing images
        for fullname in local_images:
            if '/walt-node' in fullname and fullname not in self.images:
                self.images[fullname] = NodeImage(self.c, fullname)
        # remove deleted images
        for fullname in self.images.keys():
            if fullname not in local_images:
                del self.images[fullname]
    def __getitem__(self, image_fullname):
        return self.images[image_fullname]
    def __iter__(self):
        return self.images.iterkeys()
    def __len__(self):
        return len(self.images)
    def keys(self):
        return self.images.keys()
    def iteritems(self):
        return self.images.iteritems()
