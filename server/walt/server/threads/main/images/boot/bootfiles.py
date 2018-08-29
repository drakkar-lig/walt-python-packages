import shutil, os.path, filecmp
from pkg_resources import resource_filename
from walt.common.tools import failsafe_makedirs, failsafe_symlink, do, get_mac_address
from walt.server.tools import update_template
from walt.server import const

RPI_MODELS = ('b', 'b-plus', '2-b', '3-b')
FILES = ('pc-x86-64.ipxe', 'rpi.uboot')
BOOTFILES_DIR = '/var/lib/walt/boot'
SERVER_PARAMS = dict(server_mac = get_mac_address(const.WALT_INTF))

def update_bootfiles():
    failsafe_makedirs(BOOTFILES_DIR)
    # copy scripts included in source dir
    for file_name in FILES:
        file_src = resource_filename(__name__, file_name)
        file_dst = os.path.join(BOOTFILES_DIR, file_name)
        if not os.path.exists(file_dst) or not filecmp.cmp(file_src, file_dst):
            # files differ
            shutil.copy2(file_src, file_dst)
    # update server-params.ipxe if needed.
    # in order to know if update is needed, we set, each time an
    # update is done, the modified time of the formatted file to
    # the same as the one of the original template file.
    # if times do not match, it means the original template file
    # was updated in the source code, so we should update.
    file_src = resource_filename(__name__, 'server-params.ipxe.template')
    mtime_src, atime_src = os.path.getmtime(file_src), os.path.getatime(file_src)
    file_dst = os.path.join(BOOTFILES_DIR, 'server-params.ipxe')
    update_needed = True
    if os.path.exists(file_dst):
        mtime_dst = os.path.getmtime(file_dst)
        if mtime_dst == mtime_src:
            update_needed = False
    if update_needed:
        shutil.copy(file_src, file_dst)
        update_template(file_dst, SERVER_PARAMS)
        os.utime(file_dst, (atime_src, mtime_src))
    # create rpi-<model>.uboot symlinks
    link_src = os.path.join(BOOTFILES_DIR, 'rpi.uboot')
    for rpi_model in RPI_MODELS:
        link_dst = os.path.join(BOOTFILES_DIR, 'rpi-%s.uboot' % rpi_model)
        failsafe_symlink(link_src, link_dst, force_relative=True)
