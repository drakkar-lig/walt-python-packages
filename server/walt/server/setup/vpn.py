import aiohttp
import asyncio
import dns.resolver
import os
import socket
import subprocess
import sys
import time

from aiohttp import web
from copy import deepcopy
from pathlib import Path
from plumbum.cli.terminal import prompt
from walt.doc.md import display_doc
from walt.common.formatting import columnate, framed, highlight
from walt.common.term import (
        alternate_screen_buffer,
        choose,
        clear_screen,
        wait_for_large_enough_terminal,
)
from walt.common.tools import chown_tree, do
from walt.server.tools import wait_message_read
from walt.server.vpn.const import (
        VPN_SERVER_PATH,
        VPN_ENDPOINT_PATH,
        VPN_CA_KEY,
        VPN_CA_KEY_PUB,
        VPN_SERVER_KRL,
)

EDITOR_TOP_MESSAGE = """\
Please review and validate or edit the proposed configuration of WalT VPN.
"""
MENU_NAVIGATION_TIP = "use arrow keys to browse, <enter> to select"
FQDN_ISSUE = """\
The "fully qualified domain name" of this server seems wrong or
not registered in the DNS."""
VPN_GENERIC_ISSUE_MESSAGE = """\
We cannot enable the VPN before this issue is solved.
When solved, run "walt-server-setup --edit-conf" to get
back to this VPN configuration screen."""
EXPLAIN_VPN_ENABLING = """\
-----------------------------------------------------------------
Caution: the VPN should not be enabled on a mobile WalT platform.
By enabling the VPN, you confirm this WalT server has a static
network configuration and its domain name will not change.
-----------------------------------------------------------------
"""
EXPLAIN_BOOT_MODE = """\
-----------------------------------------------------------------
If VPN nodes are installed in public places, "enforced" mode is
recommended. Otherwise, "permissive" mode is sufficient.

This choice can be reverted in the future by returning to this
setup screen (i.e., `walt-server-setup --edit-conf`).
On bootup, VPN nodes automatically reflash their EEPROM to
reflect changes in VPN settings.

For more info, return to the main menu by typing ctrl-C and
display the help page about WalT VPN.
-----------------------------------------------------------------
"""

WALT_VPN_USER = dict(
    home_dir=VPN_ENDPOINT_PATH,
    authorized_keys_pattern="""
# walt VPN secured access
cert-authority,restrict,command="walt-server-vpn-endpoint" %(ca_pub_key)s
""",
)
SSHD_CONFIG_DIR = Path("/etc/ssh/sshd_config.d")
SSHD_CONFIG_WALT = SSHD_CONFIG_DIR / "walt.conf"

# VPN entrypoint test functions
# -----------------------------
async def async_client_test_http_entrypoint(http_entrypoint):
    url = f"http://{http_entrypoint}/walt-vpn/server"
    print(f'Trying GET on "{url}"...')
    fqdn = socket.getfqdn()
    for _ in range(3):
        aiohttp_timeout = aiohttp.ClientTimeout(total=2)
        session_kwargs = dict(timeout=aiohttp_timeout)
        try:
            async with aiohttp.ClientSession(**session_kwargs) as session:
                async with session.get(url) as response:
                    response.raise_for_status()
                    body = await response.text()
                    res = body.strip()
                    if res == fqdn:
                        return (True,)
                    err = f'Mismatch, it returned "{res}" instead of "{fqdn}"!'
                    return (False, err)
        except asyncio.TimeoutError:
            await asyncio.sleep(1.0)
            continue
        except aiohttp.ClientResponseError as e:
            return (False, f"HTTP error {e.status}, {e.message}")
        except Exception as e:
            return (False, "HTTP request failed! " + str(e))
    return (False, "Timed out!")


async def async_get_fqdn(request):
    fqdn = socket.getfqdn()
    return web.Response(text=fqdn)


async def async_test_http_entrypoint(http_entrypoint):
    # start a mini web app in async mode
    app = web.Application()
    app.add_routes([web.get('/walt-vpn/server', async_get_fqdn)])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, port=80)
    await site.start()
    # check if we connecting to the given http_entrypoint
    # properly redirects to the mini web app
    res = await async_client_test_http_entrypoint(http_entrypoint)
    await runner.cleanup()
    return res


def test_http_entrypoint(http_entrypoint):
    res = asyncio.run(async_test_http_entrypoint(http_entrypoint))
    if res[0]:
        print("OK.")
        return True
    else:
        print("Failed: " + res[1])
        print("Please verify your entry, and the configuration of this web server.")
        return False


def test_ssh_entrypoint(ssh_entrypoint):
    args = ["walt-server-vpn-test-ssh-entrypoint", ssh_entrypoint]
    result = subprocess.run(args)
    return (result.returncode == 0)


def validate_ip_or_hostname(x):
    try:
        socket.getaddrinfo(x, 0)
    except Exception as e:
        print(str(e))
        return False
    return True


EP_TEST_FUNCTIONS = {
    "HTTP": test_http_entrypoint,
    "SSH": test_ssh_entrypoint,
}


# VPN settings prompt functions
# -----------------------------
def prompt_http_entrypoint():
    return prompt_proto_entrypoint("HTTP")


def prompt_ssh_entrypoint():
    return prompt_proto_entrypoint("SSH")


def prompt_proto_entrypoint(proto):
    value = prompt(
        f"Please indicate the IP or hostname of the {proto} entrypoint:",
        type=str
    )
    if not validate_ip_or_hostname(value):
        return ("KO-RETRY",)
    else:
        test_function = EP_TEST_FUNCTIONS[proto]
        if not test_function(value):
            return ("KO-RETRY",)
    return ("OK", value)


def prompt_boot_mode():
    print(EXPLAIN_BOOT_MODE)
    value = choose(
            f"Please indicate the boot mode of VPN-capable nodes:",
            ["permissive", "enforced"],
            allow_ctrl_c=True,
    )
    if value is None:
        return ("KO-ABORT",)
    else:
        print("OK.")
        return ("OK", value)


# pretty printing vpnconf
# -----------------------

CONF_ENTRIES_ENABLED = { "ssh-entrypoint": {
                             "label": "SSH entrypoint",
                             "prompt-function": prompt_ssh_entrypoint,
                         },
                         "http-entrypoint": {
                             "label": "HTTP entrypoint",
                             "prompt-function": prompt_http_entrypoint,
                         },
                         "boot-mode": {
                             "label": "VPN boot mode",
                             "prompt-function": prompt_boot_mode,
                         },
                       }
LABEL_PER_KEY_ENABLED = {
        k: info["label"]
        for k, info in CONF_ENTRIES_ENABLED.items()
}


def pprinted_value(vpnconf, k):
    return str(vpnconf.get(k, highlight("undefined")))


def pretty_print_vpnconf(vpnconf):
    if vpnconf["enabled"]:
        header = ["Enabled"] + list(LABEL_PER_KEY_ENABLED.values())
        row = ("yes",)
        row += tuple(pprinted_value(vpnconf, k) for k in CONF_ENTRIES_ENABLED)
    else:
        header = ["Enabled"]
        row = ("no",)
    conf_text = columnate([row], header)
    screen = framed("WalT VPN configuration", conf_text)
    min_width = len(screen.split("\n", maxsplit=1)[0])
    clear_screen()
    if wait_for_large_enough_terminal(min_width):
        clear_screen()
    print()
    print(EDITOR_TOP_MESSAGE)
    print(screen)


def vpnconf_is_complete(vpnconf):
    return not vpnconf["enabled"] or (len(vpnconf) == 4)


def print_vpnconf_status(context, vpnconf):
    s = "Configuration status: "
    if vpnconf_is_complete(vpnconf):
        print(s + "OK")
    else:
        print(
            s + highlight("incomplete")
        )


# main menu
# ---------

def menu_info(context, vpnconf):
    options = {}
    if vpnconf["enabled"]:
        options["disable the VPN"] = (toggle_vpn,)
        for k, label in LABEL_PER_KEY_ENABLED.items():
            verb = "change" if k in vpnconf else "define"
            options[f"{verb} the {label}"] = (define_vpn_property, k)
    else:
        options["enable the VPN"] = (toggle_vpn,)
    options["display help page about WalT VPN"] = (show_vpn_doc,)
    initial_vpnconf = context["initial_vpnconf"]
    if initial_vpnconf != vpnconf:
        options["discard changes"] = (discard_changes,)
    if vpnconf_is_complete(vpnconf):
        # configuration is complete
        options["validate and quit"] = (exit_conf,)
    return f"Main menu ({MENU_NAVIGATION_TIP}):", options


def show_vpn_doc(context, vpnconf):
    display_doc("vpn")


def discard_changes(context, vpnconf):
    vpnconf.clear()
    vpnconf.update(context["initial_vpnconf"])


def exit_conf(context, vpnconf):
    context.update(should_continue=False)


def define_vpn_property(context, vpnconf, k):
    conf_info = CONF_ENTRIES_ENABLED[k]
    prompt_function = conf_info["prompt-function"]
    while True:
        try:
            # prompt for value and check it
            res = prompt_function()
            if res[0] == "KO-RETRY":
                print("Note: type ctrl-C to abort.")
                print()
                continue
            elif res[0] == "KO-ABORT":
                raise KeyboardInterrupt
            else:
                assert res[0] == "OK"
                time.sleep(2)
                vpnconf[k] = res[1]  # validate the change
                return
        except KeyboardInterrupt:
            print()
            print("Aborted.")
            return


def has_ip_in_dns(hostname):
    for t in ("A", "AAAA"):     # IPv4 & IPv6
        try:
            dns.resolver.resolve(hostname, t)
            return True
        except Exception:
            pass
    return False


def check_valid_fqdn():
    fqdn = socket.getfqdn()
    if not "." in fqdn:
        return False, FQDN_ISSUE
    if not has_ip_in_dns(fqdn):
        return False, FQDN_ISSUE
    return (True,)


def get_default_vpnconf():
    return {
        "enabled": False,
    }


def confirm_enable_vpn():
    print(EXPLAIN_VPN_ENABLING)
    return choose(
        "Please confirm you want to enable the VPN:", {
            "Yes (static WalT platform)": True,
            "No (mobile WalT platform)": False
        }
    )


def toggle_vpn(context, vpnconf):
    if vpnconf["enabled"]:
        # disable
        vpnconf.clear()
        vpnconf["enabled"] = False
    else:
        # enable
        check = check_valid_fqdn()
        if check[0]:
            fqdn = socket.getfqdn()
            if confirm_enable_vpn():
                vpnconf.update({
                    "enabled": True,
                    "ssh-entrypoint": fqdn,
                    "http-entrypoint": fqdn,
                    "boot-mode": "permissive",
                })
        else:
            print(check[1])
            print(VPN_GENERIC_ISSUE_MESSAGE)
            print()
            print("Press <enter> to return to the menu. ", end="")
            sys.stdout.flush()
            input()


# main module entrypoints
# -----------------------
def edit_vpnconf_interactive(vpnconf):
    # vpnconf probably comes from walt.server.conf['vpn'], ensure we will not
    # modify this configuration directly by performing a deep copy of the object
    vpnconf = deepcopy(vpnconf)
    # ready for the interactive screen
    print("Entering vpn configuration editor... ", end="")
    sys.stdout.flush()
    time.sleep(2)
    context = dict(
        initial_vpnconf=deepcopy(vpnconf),
        should_continue=True,
        return_value=None,
    )
    with alternate_screen_buffer():
        while True:
            pretty_print_vpnconf(vpnconf)
            valid = print_vpnconf_status(context, vpnconf)
            print()
            menu_title, menu_options = menu_info(context, vpnconf)
            selected = choose(menu_title, menu_options)
            action = selected[0]
            action_args = selected[1:]
            print()
            action(context, vpnconf, *action_args)
            if not context["should_continue"]:
                break
    print("\rEntering vpn configuration editor... done")
    return vpnconf


def setup_vpn():
    modified = False
    home_dir = WALT_VPN_USER["home_dir"]
    # create user walt-vpn
    if not home_dir.exists():
        if Path("/var/lib/walt/vpn").exists():
            # old setup < WalT v10, migrate
            Path("/var/lib/walt/vpn").rename(home_dir)
            do(f"usermod -d {home_dir} walt-vpn")
            VPN_SERVER_PATH.mkdir(parents=True, exist_ok=True)
            for key_file in ("vpn-ca-key", "vpn-ca-key.pub"):
                orig_file = home_dir / ".ssh" / key_file
                dest_file = VPN_SERVER_PATH / key_file
                orig_file.rename(dest_file)
            chown_tree(VPN_SERVER_PATH, "root", "root")
        else:
            do(f"useradd -U -m -d {home_dir} walt-vpn")
        modified = True
    # generate VPN CA key pair
    if not VPN_CA_KEY.exists():
        VPN_CA_KEY.parent.mkdir(parents=True)
        do(f"ssh-keygen -N '' -t ecdsa -b 521 -f {VPN_CA_KEY}")
        modified = True
    # create or update authorized_keys file
    ca_pub_key = VPN_CA_KEY_PUB.read_text().strip()
    authorized_keys = (WALT_VPN_USER["authorized_keys_pattern"]
                       % dict(ca_pub_key=ca_pub_key))
    if not (home_dir / ".ssh" ).exists():
        (home_dir / ".ssh" ).mkdir(mode=0o700)
        modified = True
    authorized_keys_path = home_dir / ".ssh" / "authorized_keys"
    cur_authorized_keys = ""
    if authorized_keys_path.exists():
        cur_authorized_keys = authorized_keys_path.read_text()
    if cur_authorized_keys != authorized_keys:
        authorized_keys_path.write_text(authorized_keys)
        authorized_keys_path.chmod(0o600)
        modified = True
    # fix owner of /var/lib/walt/vpn-endpoint to 'walt-vpn'
    if modified:
        chown_tree(home_dir, "walt-vpn", "walt-vpn")
    # setup sshd for key revocation
    if not SSHD_CONFIG_WALT.exists():
        SSHD_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        SSHD_CONFIG_WALT.write_text(f"RevokedKeys {VPN_SERVER_KRL}")
    # create the key revocation list file if missing
    if not VPN_SERVER_KRL.exists():
        VPN_SERVER_PATH.mkdir(parents=True, exist_ok=True)
        do(f"ssh-keygen -k -f {VPN_SERVER_KRL}")
