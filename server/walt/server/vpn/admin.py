#!/usr/bin/env python
import os
import socket
import time

from importlib.resources import files
from plumbum.cli.terminal import prompt
from walt.common.apilink import ServerAPILink
from walt.common.term import alternate_screen_buffer, choose, clear_screen
from walt.server.vpn.const import VPN_CA_KEY_PUB

EDITOR_TOP_MESSAGE = "VPN admin tool"


def list_valid_auth_keys(context):
    auth_keys = context["auth_keys"]
    mask_revoked = auth_keys.revoked.astype(bool)
    valid_keys = auth_keys[~mask_revoked]
    if len(valid_keys) == 0:
        print("No valid VPN keys are in use.")
        print()
    else:
        mask_forgotten = valid_keys.forgotten_device.astype(bool)
        if (~mask_forgotten).sum() > 0:
            auth_keys_existing_dev = valid_keys[~mask_forgotten]
            print("The following keys are currently in use by VPN nodes:")
            print((auth_keys_existing_dev.certid + ": used by " +
                   auth_keys_existing_dev.device_label + "\n").sum())
        if mask_forgotten.sum() > 0:
            auth_keys_forgotten_dev = valid_keys[mask_forgotten]
            print("Some VPN nodes have been forgotten in the past.")
            print("(See `walt device forget --help`).")
            print("They were using the following keys you may want to revoke:")
            print((auth_keys_forgotten_dev.certid + ": was used by " +
                   auth_keys_forgotten_dev.device_label + "\n").sum())
    print()
    input("Type <enter> to return to the menu.")


def list_revoked_auth_keys(context):
    auth_keys = context["auth_keys"]
    mask_revoked = auth_keys.revoked.astype(bool)
    revoked_keys = auth_keys[mask_revoked]
    if len(revoked_keys) == 0:
        print("No VPN keys were revoked.")
    else:
        print("The following keys are revoked.")
        mask_forgotten = revoked_keys.forgotten_device.astype(bool)
        if (~mask_forgotten).sum() > 0:
            auth_keys_existing_dev = revoked_keys[~mask_forgotten]
            print((auth_keys_existing_dev.certid + ": associated to " +
                   auth_keys_existing_dev.device_label + "\n").sum())
        if mask_forgotten.sum() > 0:
            auth_keys_forgotten_dev = revoked_keys[mask_forgotten]
            print((auth_keys_forgotten_dev.certid + ": was associated to " +
                   auth_keys_forgotten_dev.device_label + "\n").sum())
    print()
    input("Type <enter> to return to the menu.")


def revoke_key(context):
    auth_keys = context["auth_keys"]
    while True:
        try:
            # prompt for value and check it
            cert_id = prompt(("Enter the key you want to revoke "
                            "(or ctrl-C to abort):"), type=str)
            match = auth_keys[auth_keys.certid == cert_id]
            if len(match) == 0:
                print("Sorry, this key does not exist.")
                continue
            auth_key = match[0]
            if auth_key.revoked:
                print("This key is already revoked.")
                cert_id = None
                break
            break  # OK
        except KeyboardInterrupt:
            print()
            print("Aborted.")
            cert_id = None
            break
    if cert_id is not None:
        # ok, revoke
        with ServerAPILink("localhost", "SSAPI") as server:
            server.revoke_vpn_auth_key(cert_id)
        # update our table
        auth_keys.revoked[auth_keys.certid == cert_id] = True
        print("Done.")
    print()
    input("Type <enter> to return to the menu.")


def validate_hostname(x):
    try:
        socket.getaddrinfo(x, 0)
    except Exception as e:
        print(str(e))
        return False
    return True


def generate_ssh_ep_script(context):
    import walt.server.vpn
    script_path = files(walt.server.vpn) / "vpn-ssh-ep-setup.sh"
    script_content = script_path.read_text() % dict(
        ca_pub_key=VPN_CA_KEY_PUB.read_text().strip(),
        walt_server=socket.getfqdn(),
    )
    with open("ssh-ep-setup.sh", "w") as f:
        f.write(script_content)
        os.fchmod(f.fileno(), 0o755)  # set it executable
    print("A script 'ssh-ep-setup.sh' has been generated in current directory.")
    print("Copy and run it on the host you want to use as a VPN SSH entrypoint.")
    print()
    input("Type <enter> to return to the menu.")


def quit_screen(context):
    context.update(should_continue=False)


def compute_menu_options(context):
    auth_keys = context["auth_keys"]
    mask_revoked = auth_keys.revoked.astype(bool)
    num_revoked = mask_revoked.sum()
    num_valid = auth_keys.size - num_revoked
    options = {
            "generate a VPN SSH entrypoint setup script":
                generate_ssh_ep_script,
            f"list valid authentication keys (count={num_valid})":
                list_valid_auth_keys,
            f"list revoked authentication keys (count={num_revoked})":
                list_revoked_auth_keys,
    }
    if num_valid > 0:
        options.update({
             "revoke an authentication key":
                revoke_key,
        })
    options.update({
             "quit this screen":
                quit_screen,
    })
    return options


def run():
    if os.geteuid() != 0:
        exit("This is only allowed to user 'root'. Exiting.")
    with ServerAPILink("localhost", "SSAPI") as server:
        auth_keys = server.get_vpn_auth_keys()
    context = dict(
        should_continue=True,
        auth_keys=auth_keys,
    )
    with alternate_screen_buffer():
        while True:
            clear_screen()
            print()
            print(EDITOR_TOP_MESSAGE)
            print()
            menu_options = compute_menu_options(context)
            action = choose("Select a command", menu_options)
            print()
            action(context)
            if not context["should_continue"]:
                break
