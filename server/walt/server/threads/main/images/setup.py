import os, shutil, os.path
from walt.common.tools import failsafe_makedirs, do
from walt.common.constants import \
        WALT_SERVER_DAEMON_PORT, WALT_SERVER_TCP_PORT
from walt.server.const import WALT_NODE_NET_SERVICE_PORT
from walt.server.threads.main.images import spec
from walt.server.tools import update_template
from walt.server.threads.main.network.tools import get_server_ip, get_dns_servers
from pkg_resources import resource_filename

# List scripts to be installed on the node and indicate
# if they contain template parameters that should be
# updated.
NODE_SCRIPTS = {'walt-env': True,
                'walt-cat': False,
                'walt-tee': False,
                'walt-notify-bootup': False,
                'walt-init': False,
                'walt-nfs-watchdog': False,
                'walt-net-service': True}

TEMPLATE_ENV = dict(
    server_ip = str(get_server_ip()),
    walt_server_rpc_port = WALT_SERVER_DAEMON_PORT,
    walt_server_logs_port = WALT_SERVER_TCP_PORT,
    walt_node_net_service_port = WALT_NODE_NET_SERVICE_PORT
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
# CAUTION: although they are stored in a different format,
# dropbear and sshd host keys must be the same.
# The dropbear key below was obtained by converting the sshd
# one using:
# $ dropbearconvert openssh dropbear \
#   /etc/ssh/ssh_host_ecdsa_key /etc/dropbear/dropbear_ecdsa_host_key
FILES = {
    '/etc/ssh/ssh_host_ecdsa_key': """\
-----BEGIN EC PRIVATE KEY-----
MHcCAQEEIDWsENxcRUkFkTi/gqNog7XbEUgJqXto4LBmR912mESMoAoGCCqGSM49
AwEHoUQDQgAE219o+OBl5qGa6iYOkHlCBbdPZs20vvIQf+bp0kIwI4Lmdq79bTTz
REHbx9/LKRGRn8z2QMq3EY9V/stQpHc68w==
-----END EC PRIVATE KEY-----
""",
    '/etc/ssh/ssh_host_ecdsa_key.pub': """\
ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBNtfaPjgZeahmuomDpB5QgW3T2bNtL7yEH/m6dJCMCOC5nau/W0080RB28ffyykRkZ/M9kDKtxGPVf7LUKR3OvM= root@rpi_ED
""",
    '/etc/dropbear/dropbear_ecdsa_host_key': '\x00\x00\x00\x13ecdsa-sha2-nistp256\x00\x00\x00\x08nistp256\x00\x00\x00A\x04\xdb_h\xf8\xe0e\xe6\xa1\x9a\xea&\x0e\x90yB\x05\xb7Of\xcd\xb4\xbe\xf2\x10\x7f\xe6\xe9\xd2B0#\x82\xe6v\xae\xfdm4\xf3DA\xdb\xc7\xdf\xcb)\x11\x91\x9f\xcc\xf6@\xca\xb7\x11\x8fU\xfe\xcbP\xa4w:\xf3\x00\x00\x00 5\xac\x10\xdc\\EI\x05\x918\xbf\x82\xa3h\x83\xb5\xdb\x11H\t\xa9{h\xe0\xb0fG\xddv\x98D\x8c',
    '/etc/hosts': """\
127.0.0.1   localhost
::1     localhost ip6-localhost ip6-loopback
ff02::1     ip6-allnodes
ff02::2     ip6-allrouters
""",
    '/root/.ssh/authorized_keys': None
}

AUTHORIZED_KEYS_PATH = '/root/.ssh/authorized_keys'
SERVER_KEY_PATH = '/root/.ssh/id_rsa'

HOSTS_FILE_CONTENT="""\
127.0.0.1   localhost
::1     localhost ip6-localhost ip6-loopback
ff02::1     ip6-allnodes
ff02::2     ip6-allrouters
"""

RESOLV_CONF_CONTENT_PATTERN = """\
nameserver %(dns_servers)s
"""

def ensure_root_key_exists():
    if not os.path.isfile(SERVER_KEY_PATH):
        do("ssh-keygen -q -t rsa -f %s -N ''" % SERVER_KEY_PATH)

def remove_if_link(path):
    if os.path.islink(path):
        os.remove(path)

def setup(image):
    mount_path = image.mount_path
    # ensure FILES var is completely defined
    if FILES['/root/.ssh/authorized_keys'] is None:
        # ensure server has a pub key
        ensure_root_key_exists()
        # we will authorize the server to connect to nodes
        with open(SERVER_KEY_PATH + '.pub') as f:
            FILES['/root/.ssh/authorized_keys'] = f.read()
    # /etc/dropbear is a symlink to /var/run/dropbear on some images.
    # * /var/run/dropbear is an absolute path, thus we should mind not
    #   being directed to server files!
    # * in this conf, the content of this directory is cleared at startup,
    #   which is not what we want.
    # We may have the same issues with /etc/ssh.
    remove_if_link(mount_path + '/etc/ssh')
    remove_if_link(mount_path + '/etc/dropbear')
    # copy files listed in variable FILES on the image
    for path, content in FILES.items():
        failsafe_makedirs(mount_path + os.path.dirname(path))
        with open(mount_path + path, 'w') as f:
            f.write(content)
    # set node DNS servers
    if os.path.exists(mount_path + '/etc/resolv.conf'):
        os.rename(mount_path + '/etc/resolv.conf', mount_path + '/etc/resolv.conf.saved')
    with open(mount_path + '/etc/resolv.conf', 'w') as f:
        f.write(RESOLV_CONF_CONTENT_PATTERN % dict(dns_servers=" ".join(get_dns_servers())))
    # copy walt scripts in <image>/bin, update template parameters
    image_bindir = mount_path + '/bin/'
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
