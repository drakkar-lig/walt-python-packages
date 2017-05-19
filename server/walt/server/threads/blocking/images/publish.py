# this implements walt image publish
def publish(requester, server, dh_peer, auth_conf, image_fullname):
    return server.docker.push(image_fullname, dh_peer, auth_conf, requester)
