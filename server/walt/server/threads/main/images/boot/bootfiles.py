import shutil, os.path, filecmp, requests
from walt.common.tools import failsafe_makedirs, failsafe_symlink, do
from pkg_resources import resource_filename

RPI_MODELS = ('b', 'b-plus', '2-b', '3-b')
FILES = ('pc-x86-64.ipxe', 'rpi.uboot')
BOOTFILES_DIR = '/var/lib/walt/boot'
PC_USB_IMAGE_URL = 'https://github.com/drakkar-lig/walt-node-boot/releases/download/v1.0/pc-usb.dd.gz'

def update_bootfiles():
    failsafe_makedirs(BOOTFILES_DIR)
    # copy scripts included in source dir
    for file_name in FILES:
        file_src = resource_filename(__name__, file_name)
        file_dst = os.path.join(BOOTFILES_DIR, file_name)
        if not filecmp.cmp(file_src, file_dst):
            # files differ
            shutil.copy2(file_src, file_dst)
    # create rpi-<model>.uboot symlinks
    link_src = os.path.join(BOOTFILES_DIR, 'rpi.uboot')
    for rpi_model in RPI_MODELS:
        link_dst = os.path.join(BOOTFILES_DIR, 'rpi-%s.uboot' % rpi_model)
        failsafe_symlink(link_src, link_dst, force_relative=True)
    # download the PC USB image
    img_file = os.path.join(BOOTFILES_DIR, 'pc-usb-v1.0.dd')
    gz_file = img_file + '.gz'
    lnk_file = os.path.join(BOOTFILES_DIR, 'pc-usb.dd')
    if not os.path.isfile(img_file):
        r = requests.get(PC_USB_IMAGE_URL, stream=True)
        if r.status_code != 200:
            raise Exception(r)
        with open(gz_file, 'wb') as f:
            for chunk in r:
                f.write(chunk)
        do('gunzip %s' % gz_file)
        failsafe_symlink(img_file, lnk_file, force_relative=True)
