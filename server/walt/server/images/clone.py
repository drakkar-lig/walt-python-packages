import requests, uuid
from walt.server.images.search import \
        Search, \
        LOCATION_WALT_SERVER, LOCATION_DOCKER_HUB, \
        LOCATION_LABEL, LOCATION_PER_LABEL

# About terminology: See comment about it in image.py.

MSG_IMAGE_NOT_REMOTE_BELONGS_TO_WS = """\
Invalid clonable image link.
Images of the form 'server:%s/<image_name>' already belong to
your working set and thus are not clonable.
"""
MSG_USE_FORCE = """\
If this is what you want, rerun with --force.
"""
MSG_INVALID_CLONABLE_LINK = """\
Invalid clonable image link. Format must be:
[server|hub]:<user>/<image_name>
(tip: walt image search [<keyword>])
"""

def parse_clonable_link(requester, clonable_link):
    bad = False
    parts = clonable_link.split(':')
    if len(parts) != 2:
        bad = True
    if not bad:
        location = parts[0]
        if location not in LOCATION_LABEL.values():
            bad = True
    if not bad:
        parts = parts[1].split('/')
        if len(parts) != 2:
            bad = True
    if not bad:
        return (LOCATION_PER_LABEL[location],
                parts[0],
                parts[1])
    if bad:
        requester.stderr.write(MSG_INVALID_CLONABLE_LINK)
        return None, None, None


def retag_image_to_requester_ws(docker, image_store, requester, source_fullname):
    source_tag = source_fullname.split(':')[1]
    dest_fullname = '%s/walt-node:%s' % (requester.username, source_tag)
    if dest_fullname in image_store:
        # an image with the target name exists...
        existing_dest_image = image_store[dest_fullname]
        # if image is mounted, umount/mount it in order to make
        # the nodes reboot with the new version
        need_mount_umount = existing_dest_image.mounted
        if need_mount_umount:
            # umount
            image_store.umount_used_image(existing_dest_image)
        # remove existing image
        docker.rmi(dest_fullname)
        # re-tag the source image
        docker.tag(source_fullname, dest_fullname)
        if need_mount_umount:
            # re-mount
            image_store.update_image_mounts()
    else:
        docker.tag(source_fullname, dest_fullname)
        image_store.register_image(dest_fullname, True)

def perform_clone(requester, docker, clonable_link, image_store, force):
    remote_location, remote_user, remote_tag = parse_clonable_link(
                                                requester, clonable_link)
    if remote_location == None:
        return # error already reported
    # actually we should validate the 3 components (user, tag and location), but
    # let's get a larger set of information (especially about other existing
    # images with the same tag, because we should take care not to overwrite
    # them)
    def validate(user, tag, location):
        return tag == remote_tag
    # search
    result = Search(docker, requester, 'Validating...').search(validate)
    # check that the requested image is in the resultset
    if      len(result) == 0 or \
            remote_user not in result[remote_tag] or \
            remote_location not in result[remote_tag][remote_user]:
        requester.stderr.write(
            'No such remote image. Use walt image search <keyword>.\n')
        return
    # filter out error cases
    users = result[remote_tag]
    locations = users[remote_user]
    would_overwrite_ws_image = False
    if requester.username == remote_user:
        if remote_location == LOCATION_WALT_SERVER:
            requester.stderr.write(
                MSG_IMAGE_NOT_REMOTE_BELONGS_TO_WS % requester.username)
            return
        else:
            if len(locations) == 2:
                would_overwrite_ws_image = True
    else:
        if requester.username in users and \
                LOCATION_WALT_SERVER in users[requester.username]:
            would_overwrite_ws_image = True
    if would_overwrite_ws_image and not force:
        ws_image_fullname = "%s/walt-node:%s" % (requester.username, remote_tag)
        image_store.warn_overwrite_image(requester, ws_image_fullname)
        requester.stderr.write(MSG_USE_FORCE)
        return
    # proceed
    remote_fullname = "%s/walt-node:%s" % (remote_user, remote_tag)
    if remote_location == LOCATION_DOCKER_HUB:
        # need to pull the image
        if LOCATION_WALT_SERVER in locations:
            # ---------------------
            # caution:
            # <u1> wants to pull hub:<u2>/<image> (and then store it as
            # server:<u1>/<image>) but server:<u2>/<image> also exists and its
            # tag would be overwritten by the docker pull operation.
            # In order to avoid that, we tag server:<u2>/<image> again
            # temporarily.
            # ---------------------
            # generate a temporary docker image name
            temp_repo = 'walt-temp-' + str(uuid.uuid4()).split('-')[0]
            temp_fullname = "%s/%s:%s" % (requester.username, temp_repo, remote_tag)
            # save server:<u2>/<image> by tagging it with the temp name
            docker.tag(remote_fullname, temp_fullname)
            # pull hub:<u2>/<image> (we get an updated version of server:<u2>/<image>)
            docker.pull(remote_fullname, requester.stdout)
            # tag the updated version of server:<u2>/<image> to server:<u1>/<image>
            # (this will make the image appear in <u1>'s working set)
            retag_image_to_requester_ws(docker, image_store, requester, remote_fullname)
            # restore the tag on server:<u2>/<image>
            docker.tag(temp_fullname, remote_fullname)
            # remove the temporary tag
            docker.untag(temp_fullname)
        else:
            # pull the image
            docker.pull(remote_fullname, requester.stdout)
            # re-tag the image with the requester username (make it appear in its WS)
            retag_image_to_requester_ws(docker, image_store, requester, remote_fullname)
            docker.untag(remote_fullname) # remove the old tag
    else:
        # tag an image of the server
        retag_image_to_requester_ws(docker, image_store, requester, remote_fullname)
    requester.stdout.write('Done.\n')

class CloneTask(object):
    def __init__(self, q, requester, **kwargs):
        self.response_q = q
        self.requester = requester
        self.kwargs = kwargs
    def perform(self):
        perform_clone(  requester = self.requester,
                        **self.kwargs)
    def handle_result(self, res):
        if isinstance(res, requests.exceptions.RequestException):
            self.requester.stderr.write(
                'Network connection to docker hub failed.\n')
            res = None
        elif isinstance(res, Exception):
            raise res   # unexpected
        self.response_q.put(res)

# this implements walt image clone
def clone(blocking, **kwargs):
    blocking.do(CloneTask(**kwargs))

