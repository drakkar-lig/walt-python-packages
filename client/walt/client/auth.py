from walt.common.crypto.blowfish import BlowFish
from walt.common.crypto.dh import DHPeer


# about password encryption:
# set comment in walt/common/crypto/__init__.py
def get_encrypted_credentials(server_pub_key, username, password):
    client_dh_peer = DHPeer()
    client_dh_peer.establish_session(server_pub_key)
    cypher = BlowFish(client_dh_peer.symmetric_key)
    encrypted_password = cypher.encrypt(password)
    return dict(
        username=username,
        encrypted_password=encrypted_password,
        client_pub_key=client_dh_peer.pub_key,
    )
