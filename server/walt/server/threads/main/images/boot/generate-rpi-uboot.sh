#!/bin/bash
set -e
# Just execute this script to generate rpi.uboot script.
if [ "$(which mkimage)" = "" ]
then
    echo "Error: u-boot's mkimage tool is needed (cf. u-boot-tools package). ABORTED."
    exit
fi

SCRIPT=$(mktemp)
cat $0 | sed '0,/SCRIPT_START$/d' > $SCRIPT
mkimage -A arm -O linux -T script -C none -n rpi-boot.scr -d $SCRIPT rpi.uboot
echo "rpi.uboot was generated in the current directory."
rm $SCRIPT
exit

######################## SCRIPT_START
setenv walt_init "/bin/walt-init"

# retrieve the dtb (device-tree-blob), or if it fails check that
# a file called "nodtb" is present.
# (this allows to avoid wrongly interpreting a failed tftp transfer)
if tftp ${fdt_addr_r} ${serverip}:nodes/${ethaddr}/${node_model}/dtb
then
    setenv has_dtb '1'
else
    echo 'Could not download the dtb file.'
    echo 'Checking if a file called nodtb exists.'
    if tftp ${fdt_addr_r} ${serverip}:nodes/${ethaddr}/${node_model}/nodtb
    then
        setenv has_dtb '0'
    else
        reset
    fi
fi

# retrieve the kernel
tftp ${kernel_addr_r} ${serverip}:nodes/${ethaddr}/${node_model}/kernel || reset

# compute kernel command line args
setenv nfs_root "${serverip}:/var/lib/walt/nodes/${ethaddr}"
setenv nfs_bootargs "root=/dev/nfs nfsroot=${nfs_root},nfsvers=3,acregmax=5"
setenv console_bootargs "console=ttyAMA0,115200 console=tty1"
setenv rpi_bootargs "smsc95xx.macaddr=${ethaddr}"
setenv walt_bootargs "walt.node.model=${node_model} walt.server.ip=${serverip}"
setenv other_bootargs "init=${walt_init} ip=dhcp panic=15"
setenv bootargs "$nfs_bootargs $console_bootargs\
 $rpi_bootargs $walt_bootargs $other_bootargs"

# boot
if test ${has_dtb} = '0'
then
    echo 'This walt image apparently has no dtb.'
    echo 'Booting kernel...'
    bootz ${kernel_addr_r} || reset
else
    echo 'Booting kernel...'
    # second argument is for the ramdisk ("-" means none)
    bootz ${kernel_addr_r} - ${fdt_addr_r} || reset
fi
