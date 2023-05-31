import json
import subprocess


def dev_has_given_child_name(dev_info, child_name):
    if "children" not in dev_info:
        return False
    for child_dev_info in dev_info["children"]:
        if child_dev_info["name"] == child_name:
            return True
        if dev_has_given_child_name(child_dev_info, child_name):
            return True
    return False


def get_grub_boot_disk():
    try:
        p = subprocess.run(
            "grub-probe -t disk /boot".split(), capture_output=True, text=True
        )
        boot_device = p.stdout.strip()
        if not boot_device.startswith("/dev/mapper"):
            return boot_device
        boot_device_name = boot_device[len("/dev/mapper/") :]
        p = subprocess.run(
            "lsblk --json --output name".split(), capture_output=True, text=True
        )
        devices_info = json.loads(p.stdout)
        for dev_info in devices_info["blockdevices"]:
            if dev_has_given_child_name(dev_info, boot_device_name):
                return "/dev/" + dev_info["name"]
    except Exception:
        pass
    return None
