import os
import os.path
import shutil
from collections import OrderedDict
from pathlib import Path

from pkg_resources import resource_filename
from walt.common.constants import (
    UNSECURE_ECDSA_KEYPAIR,
    WALT_SERVER_DAEMON_PORT,
    WALT_SERVER_TCP_PORT,
)
from walt.common.tools import do, failsafe_makedirs, failsafe_symlink, get_mac_address
from walt.server import spec
from walt.server.const import WALT_INTF, WALT_NODE_NET_SERVICE_PORT
from walt.server.tools import get_server_ip, update_template

# List scripts to be installed on the node and indicate
# * if they contain template parameters that should be updated
# * if they should be moved to directory "/bin/_walt_internal_/"
NODE_SCRIPTS = {
    "walt-env": (True, False),
    "walt-log-echo": (False, False),
    "walt-log-cat": (False, False),
    "walt-log-tee": (False, False),
    "walt-echo": (False, False),
    "walt-cat": (False, False),
    "walt-tee": (False, False),
    "walt-timeout": (False, True),
    "walt-rpc": (True, True),
    "walt-clock-sync": (False, True),
    "walt-notify-bootup": (False, True),
    "walt-init": (False, False),
    "walt-fs-watchdog": (False, True),
    "walt-net-service": (False, True),
    "walt-net-service-handler": (False, True),
    "walt-tar-send": (False, True),
    "walt-boot-modes": (False, True),
    "walt-script-common": (False, True),
    "walt-log-script": (False, True),
    "walt-init-rootfs": (False, True),
    "walt-init-rootfs-main": (False, True),
    "walt-init-finalfs": (False, True),
    "walt-init-nbd": (False, True),
    "walt-dump-diff-tar": (False, True),
}

TEMPLATE_ENV = dict(
    server_mac=get_mac_address(WALT_INTF),
    server_ip=str(get_server_ip()),
    walt_server_rpc_port=WALT_SERVER_DAEMON_PORT,
    walt_server_logs_port=WALT_SERVER_TCP_PORT,
    walt_server_notify_bootup_port=WALT_SERVER_TCP_PORT,
    walt_node_net_service_port=WALT_NODE_NET_SERVICE_PORT,
)

RESOLV_CONF = """
domain walt
search walt.
nameserver %(nameserver)s
"""

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
    "/etc/ssh/ssh_host_ecdsa_key": UNSECURE_ECDSA_KEYPAIR["openssh-priv"],
    "/etc/ssh/ssh_host_ecdsa_key.pub": UNSECURE_ECDSA_KEYPAIR["openssh-pub"],
    "/etc/dropbear/dropbear_ecdsa_host_key": UNSECURE_ECDSA_KEYPAIR["dropbear"],
    "/etc/hosts": b"""\
127.0.0.1   localhost
::1     localhost ip6-localhost ip6-loopback
ff02::1     ip6-allnodes
ff02::2     ip6-allrouters
""",
    "/root/.ssh/authorized_keys": None,
}

AUTHORIZED_KEYS_PATH = "/root/.ssh/authorized_keys"
SERVER_KEY_PATH = "/root/.ssh/id_rsa"

HOSTS_FILE_CONTENT = """\
127.0.0.1   localhost
::1     localhost ip6-localhost ip6-loopback
ff02::1     ip6-allnodes
ff02::2     ip6-allrouters
"""


def script_path(script_name):
    return resource_filename(__name__, script_name)


def ensure_root_key_exists():
    if not os.path.isfile(SERVER_KEY_PATH):
        do("ssh-keygen -q -t rsa -f %s -N ''" % SERVER_KEY_PATH)


def remove_if_link(path):
    if os.path.islink(path):
        os.remove(path)


def fix_ptp(mount_path, img_print):
    changed = False
    if not os.path.exists(mount_path + "/etc/ptpd.conf"):
        return
    with open(mount_path + "/etc/ptpd.conf") as ptpfile:
        ptpconf = ptpfile.read()
    if "ptpengine:" not in ptpconf:
        return  # probably not the PTP implementation we know
    conf = OrderedDict()
    for confline in ptpconf.splitlines():
        confname, confval = confline.split("=")
        conf[confname.strip()] = confval.strip()
    if "ptpengine:ip_mode" not in conf or conf["ptpengine:ip_mode"] != "hybrid":
        img_print("forcing hybrid ip_mode in ptp configuration.")
        conf["ptpengine:ip_mode"] = "hybrid"
        changed = True
    if (
        "ptpengine:log_delayreq_interval" not in conf
        or int(conf["ptpengine:log_delayreq_interval"]) < 3
    ):
        img_print("setting delayreq_interval to 8s in ptp configuration.")
        conf["ptpengine:log_delayreq_interval"] = "3"
        changed = True
    if changed:
        with open(mount_path + "/etc/ptpd.conf", "w") as ptpfile:
            for confname, confval in conf.items():
                ptpfile.write("%s=%s\n" % (confname, confval))


# boot files (in directory /boot) are accessed using TFTP,
# thus the root of absolute symlinks will be the TFTP root
# (/var/lib/walt), not the root of the image.
# Function fix_absolute_symlinks() replaces them with relative
# symlinks targeting the expected file taking the image root
# as reference.
def fix_if_absolute_symlink(image_root, path, img_print):
    if os.path.islink(path):
        target = os.readlink(path)
        if target.startswith("/"):
            img_print(("fixing " + path + " target (" + target + ")"))
            target = image_root + target
            failsafe_symlink(target, path, force_relative=True)
        # recursively fix the target if it is a symlink itself
        fix_if_absolute_symlink(image_root, target, img_print)


def fix_absolute_symlinks(image_root, dirpath, img_print):
    for root, dirs, files in os.walk(dirpath):
        for name in files:
            path = os.path.join(root, name)
            fix_if_absolute_symlink(image_root, path, img_print)


def update_timezone(mount_path):
    server_etc_localtime = Path("/etc/localtime")
    assert server_etc_localtime.is_symlink()
    tz_file = str(server_etc_localtime.readlink())
    image_tz_file = Path(mount_path + tz_file)
    if not image_tz_file.exists():
        # timezone file missing in image, abort
        return
    image_etc_localtime = Path(mount_path + "/etc/localtime")
    if image_etc_localtime.exists():
        if not image_etc_localtime.is_symlink():
            # unexpected OS conf
            return
        image_etc_localtime.unlink()
    elif not image_etc_localtime.parent.exists():
        # unexpected OS conf
        return
    image_etc_localtime.symlink_to(tz_file)


def setup(image_id, mount_path, image_size_kib, img_print):
    # ensure FILES var is completely defined
    if FILES["/root/.ssh/authorized_keys"] is None:
        # ensure server has a pub key
        ensure_root_key_exists()
        # we will authorize the server to connect to nodes
        FILES["/root/.ssh/authorized_keys"] = Path(
            SERVER_KEY_PATH + ".pub"
        ).read_bytes()
    # /etc/dropbear is a symlink to /var/run/dropbear on some images.
    # * /var/run/dropbear is an absolute path, thus we should mind not
    #   being directed to server files!
    # * in this conf, the content of this directory is cleared at startup,
    #   which is not what we want.
    # We may have the same issues with /etc/ssh.
    remove_if_link(mount_path + "/etc/ssh")
    remove_if_link(mount_path + "/etc/dropbear")
    # copy files listed in variable FILES on the image
    for path, content in FILES.items():
        failsafe_makedirs(mount_path + os.path.dirname(path))
        Path(mount_path + path).write_bytes(content)
    # ensure /etc/hosts has correct rights
    os.chmod(mount_path + "/etc/hosts", 0o644)
    # update /etc/resolv.conf
    resolv_conf = Path(mount_path + "/etc/resolv.conf")
    if resolv_conf.exists():
        resolv_conf.rename(resolv_conf.parent / "resolv.conf.saved")
    resolv_conf.write_text(RESOLV_CONF % dict(nameserver=get_server_ip()))
    if os.path.isfile(mount_path + "/etc/hostname") and not os.path.islink(
        mount_path + "/etc/hostname"
    ):
        os.remove(mount_path + "/etc/hostname")  # probably a residual of image build
    # fix absolute symlinks in /boot
    fix_absolute_symlinks(mount_path, mount_path + "/boot", img_print)
    # fix compatbility with old walt-node packages
    if os.path.exists(mount_path + "/usr/local/bin/walt-echo"):
        os.remove(mount_path + "/usr/local/bin/walt-echo")
    # copy walt scripts in <image>/bin/ or <image>/bin/_walt_internal_/,
    # update template parameters
    image_bindir = mount_path + "/bin/"
    image_widir = image_bindir + '_walt_internal_/'
    Path(image_widir).mkdir(exist_ok=True)
    env = dict(walt_image_id=image_id,
               walt_image_size_kib=image_size_kib,
               **TEMPLATE_ENV)
    for script_name, script_info in NODE_SCRIPTS.items():
        template, internal = script_info
        if internal:
            dst_dir = image_widir
        else:
            dst_dir = image_bindir
        shutil.copy(script_path(script_name), dst_dir)
        if template:
            update_template(dst_dir + script_name, env)
    # read image spec file if any
    image_spec = spec.read_image_spec(mount_path)
    if image_spec is not None:
        # update template files specified there
        spec.update_templates(mount_path, image_spec, env)
        # update features matching those of the server
        spec.enable_matching_features(mount_path, image_spec, img_print)
    # copy server spec file, just in case
    spec.copy_server_spec_file(mount_path)
    # fix PTP conf regarding unicast default mode too verbose on LAN
    fix_ptp(mount_path, img_print)
    # update timezone if the OS is using the standard Linux setup
    update_timezone(mount_path)
