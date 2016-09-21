from walt.common.crypto.dh import DHPeer
from walt.common.crypto.blowfish import BlowFish
from walt.client.config import conf

# about password encryption:
# set comment in walt/common/crypto/__init__.py
def get_auth_conf(server):
    client_dh_peer = DHPeer()
    server_dh_peer_id, server_pub_key = server.create_dh_peer()
    client_dh_peer.establish_session(server_pub_key)
    server.establish_dh_session(server_dh_peer_id, client_dh_peer.pub_key)
    cypher = BlowFish(client_dh_peer.symmetric_key)
    encrypted_password = cypher.encrypt(conf['password'])
    return dict(
        username = conf['username'],
        encrypted_password = encrypted_password,
        dh_peer_id = server_dh_peer_id
    )
