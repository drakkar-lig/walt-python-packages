from walt.server.threads.blocking.images.metadata import \
                        update_user_metadata_for_image

# this implements walt image publish
def publish(requester, server, dh_peer, auth_conf, image_fullname):
    # push image
    server.docker.hub.push(image_fullname, dh_peer, auth_conf, requester)
    # update user metadata ('walt_metadata' image on user's hub account)
    update_user_metadata_for_image(server.docker, dh_peer, auth_conf,
                                   requester, image_fullname)
