import os, shutil
from walt.common.tools import failsafe_makedirs
from walt.common.constants import \
        WALT_SERVER_DAEMON_PORT, WALT_SERVER_TCP_PORT
from walt.server.threads.main.images import spec
from walt.server.tools import update_template
from walt.server.threads.main.network.tools import get_server_ip
from pkg_resources import resource_filename

# List scripts to be installed on the node and indicate
# if they contain template parameters that should be
# updated.
NODE_SCRIPTS = {'walt-env': True,
                'walt-cat': False,
                'walt-tee': False,
                'walt-notify-bootup': False,
                'walt-init': False }

TEMPLATE_ENV = dict(
    server_ip = str(get_server_ip()),
    walt_server_rpc_port = WALT_SERVER_DAEMON_PORT,
    walt_server_logs_port = WALT_SERVER_TCP_PORT
)

# when using walt, nodes often get new operating system
# images, and usually each of these images has a new
# authentication key.
# this causes annoyance when using ssh to connect from the
# server to a node.
# we do not really need to secure access to nodes, since
# they are very temporary environments, and since the walt
# network is in a dedicated, separated vlan.
# thus, when mounting an image, we will overwrite its
# authentication key with the following one, which will
# remain constant.
NODE_ECDSA_KEYPAIR = dict(
    private_key = """\
-----BEGIN EC PRIVATE KEY-----
MHcCAQEEIDWsENxcRUkFkTi/gqNog7XbEUgJqXto4LBmR912mESMoAoGCCqGSM49
AwEHoUQDQgAE219o+OBl5qGa6iYOkHlCBbdPZs20vvIQf+bp0kIwI4Lmdq79bTTz
REHbx9/LKRGRn8z2QMq3EY9V/stQpHc68w==
-----END EC PRIVATE KEY-----
""",
    private_key_path = '/etc/ssh/ssh_host_ecdsa_key',
    public_key = """\
ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBNtfaPjgZeahmuomDpB5QgW3T2bNtL7yEH/m6dJCMCOC5nau/W0080RB28ffyykRkZ/M9kDKtxGPVf7LUKR3OvM= root@rpi_ED
""",
    public_key_path = '/etc/ssh/ssh_host_ecdsa_key.pub'
)

AUTHORIZED_KEYS_PATH = '/root/.ssh/authorized_keys'
SERVER_PUBKEY_PATH = '/root/.ssh/id_dsa.pub'

HOSTS_FILE_CONTENT="""\
127.0.0.1   localhost
::1     localhost ip6-localhost ip6-loopback
ff02::1     ip6-allnodes
ff02::2     ip6-allrouters
"""

def setup(image):
    mount_path = image.mount_path
    # set node pub and priv key
    with open(mount_path + NODE_ECDSA_KEYPAIR['private_key_path'], 'w') as f:
        f.write(NODE_ECDSA_KEYPAIR['private_key'])
    with open(mount_path + NODE_ECDSA_KEYPAIR['public_key_path'], 'w') as f:
        f.write(NODE_ECDSA_KEYPAIR['public_key'])
    # authorize server pub key
    failsafe_makedirs(mount_path + os.path.dirname(AUTHORIZED_KEYS_PATH))
    shutil.copy(SERVER_PUBKEY_PATH, mount_path + AUTHORIZED_KEYS_PATH)
    # copy walt scripts in <image>/usr/local/bin, update template parameters
    image_bindir = mount_path + '/usr/local/bin/'
    for script_name, template in NODE_SCRIPTS.items():
        script_path = resource_filename(__name__, script_name)
        shutil.copy(script_path, image_bindir)
        if template:
            update_template(image_bindir + script_name, TEMPLATE_ENV)
    # read image spec file if any
    image_spec = spec.read_image_spec(mount_path)
    if image_spec != None:
        # update template files specified there
        spec.update_templates(mount_path, image_spec, TEMPLATE_ENV)
        # update features matching those of the server
        spec.enable_matching_features(image, image_spec)
    # copy server spec file, just in case
    spec.copy_server_spec_file(mount_path)
    # create hosts file
    with open(mount_path + '/etc/hosts', 'w') as f:
        f.write(HOSTS_FILE_CONTENT)

