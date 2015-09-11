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
MSG_WOULD_OVERWRITE_WS_IMAGE = """\
This would overwrite image '%s' of your working set.
If this is what you want, you should remove or rename this image
before proceeding again.
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

def perform_clone(c, requester, clonable_link, image_store):
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
    if requester.username == remote_user:
        if remote_location == LOCATION_WALT_SERVER:
            requester.stderr.write(
                MSG_IMAGE_NOT_REMOTE_BELONGS_TO_WS % requester.username)
            return
        else:
            if len(locations) == 2:
                requester.stderr.write(MSG_WOULD_OVERWRITE_WS_IMAGE % remote_tag)
                return
    else:
        if requester.username in users and \
                LOCATION_WALT_SERVER in users[requester.username]:
            requester.stderr.write(MSG_WOULD_OVERWRITE_WS_IMAGE % remote_tag)
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
            c.tag(image=remote_fullname, repository=new_repo, tag=remote_tag)
            # restore the tag on server:<u2>/<image>
            c.tag(image=temp_fullname, repository=remote_repo, tag=remote_tag)
            # remove the temporary tag
            c.remove_image(image=temp_fullname, force=True)
        else:
            # pull the image
            pull(c, requester, remote_user, remote_tag)
            # re-tag the image with the requester username (make it appear in its WS)
            c.tag(image=remote_fullname, repository=new_repo, tag=remote_tag)
            c.remove_image(image=remote_fullname, force=True) # remove the old tag
    else:
        # tag an image of the server
        c.tag(image=remote_fullname, repository=new_repo, tag=remote_tag)
    image_store.refresh()
    requester.stdout.write('Done.\n')

class CloneTask(object):
    def __init__(self, q, c, requester, clonable_link, image_store):
        self.response_q = q
        self.docker = c
        self.requester = requester
        self.clonable_link = clonable_link
        self.image_store = image_store
    def perform(self):
        perform_clone(
                self.docker,
                self.requester,
                self.clonable_link,
                self.image_store)
    def handle_result(self, res):
        self.response_q.put(res)

# this implements walt image clone
def clone(q, blocking_manager, c, requester, clonable_link, image_store):
    blocking_manager.do(CloneTask(q, c, requester, clonable_link, image_store))

