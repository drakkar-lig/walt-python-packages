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
    def values(self):
        return self.images.values()
    # look for an image belonging to the requester.
    # The 'expected' parameter allows to specify if we expect a matching
    # result (expected = True), no matching result (expected = False),
    # or if both options are ok (expected = None).
    # If expected is True or False and the result does not match expectation,
    # an error message will be printed.
    def get_user_image_from_tag(self, requester, image_tag, expected = True):
        found = None
        for image in self.images.values():
            if image.tag == image_tag and image.user == requester.username:
                found = image
        if expected == True and found is None:
            requester.stderr.write(
                "Error: No such image '%s'. (tip: walt image show)\n" % image_tag)
        if expected == False and found is not None:
            requester.stderr.write(
                "Error: Image '%s' already exists.\n" % image_tag)
        return found
    def get_user_unmounted_image_from_tag(self, requester, image_tag):
        image = self.get_user_image_from_tag(requester, image_tag)
        if image:   # otherwise issue is already reported
            if image.mounted:
                requester.stderr.write('Sorry, cannot proceed because the image is mounted.\n')
                return None
        return image
