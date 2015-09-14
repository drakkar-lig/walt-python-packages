import requests, uuid
from walt.server.images.search import \
        Search, \
        LOCATION_WALT_SERVER, LOCATION_DOCKER_HUB, \
        LOCATION_LABEL, LOCATION_PER_LABEL
from walt.server.tools import \
        display_transient_label, hide_transient_label

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

def pull(c, requester, user, tag):
    image_name = '%s/walt-node' % user
    for idx, line in enumerate(
                c.pull(
                    image_name,
                    tag=requests.utils.quote(tag),
                    stream=True)):
        progress = "-/|\\"[idx % 4]
        label = 'Downloading... %s\r' % progress
        display_transient_label(requester.stdout, label)
    hide_transient_label(requester.stdout, label)

def retag_image(c, image_store, requester, source_fullname):
    source_image = image_store[source_fullname]
    tag = source_image.tag
    dest_repo = '%s/walt-node' % requester.username
    dest_fullname = '%s:%s' % (dest_repo, tag)
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
        c.remove_image(image=dest_fullname, force=True)
        # re-tag the source image
        c.tag(image=source_fullname, repository=dest_repo, tag=tag)
        if need_mount_umount:
            # re-mount
            image_store.update_image_mounts()
    else:
        c.tag(image=source_fullname, repository=dest_repo, tag=tag)

def perform_clone(c, requester, clonable_link, image_store, force):
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
    result = Search(c, requester, 'Validating...').search(validate)
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
    remote_repo = "%s/%s" % (remote_user, 'walt-node')
    remote_fullname = "%s:%s" % (remote_repo, remote_tag)
    new_repo = '%s/walt-node' % requester.username
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
            temp_fullname = "%s:%s" % (temp_repo, remote_tag)
            # save server:<u2>/<image> by tagging it with the temp name
            c.tag(image=remote_fullname, repository=temp_repo, tag=remote_tag)
            # pull hub:<u2>/<image> (we get an updated version of server:<u2>/<image>)
            pull(c, requester, remote_user, remote_tag)
            # tag the updated version of server:<u2>/<image> to server:<u1>/<image>
            # (this will make the image appear in <u1>'s working set)
            retag_image(c, image_store, requester, remote_fullname)
            # restore the tag on server:<u2>/<image>
            c.tag(image=temp_fullname, repository=remote_repo, tag=remote_tag)
            # remove the temporary tag
            c.remove_image(image=temp_fullname, force=True)
        else:
            # pull the image
            pull(c, requester, remote_user, remote_tag)
            # re-tag the image with the requester username (make it appear in its WS)
            retag_image(c, image_store, requester, remote_fullname)
            c.remove_image(image=remote_fullname, force=True) # remove the old tag
    else:
        # tag an image of the server
        retag_image(c, image_store, requester, remote_fullname)
    image_store.refresh()
    requester.stdout.write('Done.\n')

class CloneTask(object):
    def __init__(self, q, *args):
        self.response_q = q
        self.args = args
    def perform(self):
        perform_clone(*self.args)
    def handle_result(self, res):
        self.response_q.put(res)

# this implements walt image clone
def clone(q, blocking_manager, *args):
    blocking_manager.do(CloneTask(q, *args))

