import re
import socket
import sys
import time
from collections import defaultdict
from copy import deepcopy

from plumbum.cli.terminal import prompt
from walt.doc.md import display_doc
from walt.common.formatting import columnate, framed, highlight
from walt.common.term import (
        alternate_screen_buffer,
        choose,
        clear_screen,
        wait_for_large_enough_terminal,
)

EDITOR_TOP_MESSAGE = """\
Please review and validate or edit the proposed configuration of image registries.
"""
CONF_TEXT_NO_REGISTRIES = """\
No image registries are defined yet.
WalT needs at least one in order to download default images."""
MENU_NAVIGATION_TIP = "use arrow keys to browse, <enter> to select"

HUB_REPOCONF = {
    "label": "hub",
    "api": "docker-hub",
    "description": "Public registry at hub.docker.com",
}
DEFAULT_PORT = 443
DEFAULT_PROTOCOL = "https"
DEFAULT_AUTH = "basic"
MAX_DESC_LEN = 35


# tools
# -----
def printed_reg_value(reg, k):
    v = str(reg.get(k, highlight("undefined")))
    if v in ("True", "False"):
        v = v.lower()
    return v


# pretty printing regconf
# ------------------------
def pretty_print_regconf(regconf):
    if len(regconf) == 0:
        conf_text = CONF_TEXT_NO_REGISTRIES
    else:
        header = ["label", "api", "description", "configuration"]
        rows = []
        for reg in regconf:
            if reg.get("label", "") == "hub":
                reg_config = "<not-editable>"
            else:
                props = ("host", "port", "protocol", "auth")
                if reg['api'] == 'jfrog-artifactory':
                    props += ("repository",)
                reg_config = " ".join(
                    f"{k}={printed_reg_value(reg, k)}"
                    for k in props
                )
            rows.append(
                (
                    printed_reg_value(reg, "label"),
                    reg["api"],
                    reg["description"],
                    reg_config,
                )
            )
        conf_text = columnate(rows, header)
    screen = framed("WalT image registries", conf_text)
    min_width = len(screen.split("\n", maxsplit=1)[0])
    clear_screen()
    if wait_for_large_enough_terminal(min_width):
        clear_screen()
    print()
    print(EDITOR_TOP_MESSAGE)
    print(screen)


def print_regconf_status(context, regconf):
    s = "Configuration status: "
    if len(regconf) == 0:
        print(
            s + highlight("incomplete") + " (tip: define at least one image registry)"
        )
        return False  # incomplete
    undefined = []
    for reg in regconf:
        if reg.get("label", "") == "hub":
            continue
        api = reg["api"]
        possibly_undefined = {
                "docker-registry-v2": ("label", "host"),
                "jfrog-artifactory": ("label", "host", "repository"),
        }[api]
        for k in possibly_undefined:
            if k not in reg:
                undefined.append(k)
    if len(undefined) > 0:
        print(
            s + highlight("incomplete") + " (tip: define " + ", ".join(undefined) + ")"
        )
        return False  # incomplete
    labels = set()
    for reg in regconf:
        label = reg["label"]
        if label in labels:
            explain = f'"{label}" cannot be used several times as a registry label.'
            print(s + highlight("invalid") + "\n" + explain)
            return False  # invalid
        labels.add(label)
    # we cannot have two registries at the same <host>:<port>, except
    # JFrog which can support several registries on the same server,
    # each one with a different "repository" name.
    api_per_host_port = {}
    jfrog_repos_per_host_port = defaultdict(set)
    for reg in regconf:
        if reg["label"] == "hub":
            continue
        host, port, api = reg["host"], reg["port"], reg["api"]
        other_registry_api = api_per_host_port.get((host, port))
        if other_registry_api is not None:
            if api != "jfrog-artifactory" or other_registry_api != "jfrog-artifactory":
                explain = ('Several registries are using the same '
                           f'location "{host}:{port}".')
                print(s + highlight("invalid") + "\n" + explain)
                return False  # invalid
            # we have two JFrog registries at the same (host, port) location.
            # check that they target a different "repository" name.
            jfrog_repo = reg["repository"]
            other_jfrog_repos = jfrog_repos_per_host_port[(host, port)]
            if jfrog_repo in other_jfrog_repos:
                explain = (f'The JFrog repository "{jfrog_repo}" '
                           f'at location "{host}:{port}" is listed twice.')
                print(s + highlight("invalid") + "\n" + explain)
                return False  # invalid
        api_per_host_port[(host, port)] = api
        if api == "jfrog-artifactory":
            jfrog_repos_per_host_port[(host, port)].add(reg["repository"])
    print(s + "OK")
    return True  # valid


# main menu
# ---------


def select_main_menu(context, regconf):
    context["menu_info_function"] = main_menu_info


def main_menu_info(context, regconf, valid):
    options = {}
    regconf_per_label = {reg["label"]: reg for reg in regconf}
    for i, reg in enumerate(regconf):
        label = reg["label"]
        if label == "hub":
            continue  # configuration of the hub cannot be modified
        options.update(
            {
                f'edit or remove "{label}" configuration': (
                    select_reg_edit_menu,
                    i,
                    False,
                )
            }
        )
    if "hub" in regconf_per_label:
        options.update({"disable the docker hub registry": (disable_docker_hub,)})
    else:
        options.update({"enable the docker hub registry": (define_docker_hub,)})
    options.update({"connect to a custom docker image registry": (define_custom_reg,)})
    options.update({"connect to a JFrog Artifactory instance": (define_jfrog_reg,)})
    options.update({"display help page about WalT registries": (show_registries_doc,)})
    if context["initial_regconf"] != regconf:
        options.update({"discard changes": (discard_changes,)})
    if valid:
        options["validate and quit"] = (exit_conf,)
    return f"Main menu ({MENU_NAVIGATION_TIP}):", options


def disable_docker_hub(context, regconf):
    del regconf[0]  # hub is always the first reg


def define_docker_hub(context, regconf):
    regconf.insert(0, HUB_REPOCONF)


def define_custom_reg(context, regconf):
    i = len(regconf)
    regconf.append(
        {
            "api": "docker-registry-v2",
            "description": "Local registry",
            "port": DEFAULT_PORT,
            "protocol": DEFAULT_PROTOCOL,
            "auth": DEFAULT_AUTH,
        }
    )
    select_reg_edit_menu(context, regconf, i, True)


def define_jfrog_reg(context, regconf):
    i = len(regconf)
    regconf.append(
        {
            "api": "jfrog-artifactory",
            "description": "Local registry",
            "port": DEFAULT_PORT,
            "protocol": DEFAULT_PROTOCOL,
            "auth": DEFAULT_AUTH,
        }
    )
    select_reg_edit_menu(context, regconf, i, True)


def show_registries_doc(context, regconf):
    display_doc("registries")


def discard_changes(context, regconf):
    regconf.clear()
    regconf.extend(context["initial_regconf"])


def exit_conf(context, regconf):
    context.update(should_continue=False)


# registry edit menu
# ------------------


def select_reg_edit_menu(context, regconf, i, is_new):
    context["menu_info_function"] = lambda context, regconf, valid: edit_reg_menu_info(
        context, regconf, i, is_new
    )


def edit_reg_menu_info(context, regconf, i, is_new):
    # if we are here, we know we are editing a custom reg or a jfrog reg,
    # not the hub which is not editable.
    reg = regconf[i]
    if is_new:
        reg_name = "New registry"
    else:
        reg_name = '"' + reg["label"] + '"'
    options = {}
    props = ("label", "description", "host", "port", "protocol", "auth")
    if reg['api'] == 'jfrog-artifactory':
        props += ("repository",)
    for k in props:
        verb = "change" if k in reg else "define"
        options.update(
            {f"{reg_name} -- {verb} the {k} property": (define_reg_property, i, k)}
        )
    options.update({f"{reg_name} -- remove it": (remove_custom_reg, i)})
    if len(set(props) - set(reg.keys())) == 0:
        # fully defined
        options.update(
            {"Validate and return to main menu": (validate_registry_changes, i)}
        )
    return f"{reg_name} configuration menu ({MENU_NAVIGATION_TIP}):", options


def validate_registry_changes(context, regconf, i):
    # reorder registry attributes to ensure they will follow the expected order in the
    # configuration file
    # (note: python dictionaries record the order their entries were inserted)
    reg = regconf[i]
    for prop in ("label", "api", "description", "host", "port", "protocol", "auth",
                 "repository"):
        if prop in reg:
            reg[prop] = reg.pop(prop)
    # return to main menu
    select_main_menu(context, regconf)


def define_reg_property(context, regconf, i, k):
    reg = regconf[i]
    value = None
    if k == "label":
        print("Note: the label you enter will be used to identify this "
              "registry in walt commands.\n"
              "So a short label is preferred, e.g. 'local', 'local-jfrog', etc.")
    while True:
        try:
            # prompt for value and check it
            if k == "label":
                value = prompt("Please enter a label for this registry:", type=str)
                if len(re.sub("[a-z0-9-]", "", value)) > 0:
                    print(
                        'Sorry, only lowercase chars, digits, and dash ("-") are'
                        " allowed."
                    )
                    value = None
                elif value in ("hub", "walt", "docker"):
                    print(f'Value "{value}" is reserved.')
                    value = None
            elif k == "description":
                value = prompt(
                    "Please enter a short description for this registry:", type=str
                )
                if len(value) == 0:
                    print("Sorry, empty description is not allowed.")
                    value = None
                elif len(value) > MAX_DESC_LEN:
                    print(
                        "Sorry, the description should not exceed"
                        f" {MAX_DESC_LEN} chars."
                    )
                    value = None
            elif k == "host":
                value = prompt(
                    "Please indicate the IP or hostname of this registry:", type=str
                )
                if not validate_ip_or_hostname(value):
                    value = None
            elif k == "port":
                value = prompt(
                    "Please indicate the port number of this registry (e.g., 5000):",
                    type=int,
                )
            elif k == "protocol":
                value = choose(
                    "Select the protocol to access this registry:",
                    {
                        "          https: HTTPS protocol": "https",
                        "           http: HTTP protocol": "http",
                        "https-no-verify: HTTPS protocol without certificate checks": (
                            "https-no-verify"
                        ),
                    },
                )
            elif k == "auth":  # toggle between none and basic
                value = choose(
                    "Select the authentication mode for this registry:",
                    {
                        "basic: Basic HTTP authentication": "basic",
                        "none: No user authentication (anonymous access)": "none",
                    },
                )
            # the jfrog-repository is handled similarly to a team account
            # on the docker hub, API-wise.
            elif k == "repository":  # jfrog-repository (similar to a team account)
                value = prompt(
                    "Please indicate the name of the Repository to push/pull to, "
                    "on this JFrog registry: ", type=str
                )
                if len(value) == 0:
                    print("Invalid entry.")
                    value = None
            # exit or loop again
            if value is None:
                print("Note: type ctrl-C to abort.")
                print()
                continue
            else:
                reg[k] = value  # validate the change
                return
        except KeyboardInterrupt:
            print()
            print("Aborted.")
            return


def validate_ip_or_hostname(x):
    try:
        socket.getaddrinfo(x, 0)
    except Exception as e:
        print(str(e))
        return False
    return True


def remove_custom_reg(context, regconf, i):
    del regconf[i]
    select_main_menu(context, regconf)


# main module entrypoints
# -----------------------


def get_default_regconf():
    return [HUB_REPOCONF]


def edit_regconf_interactive(regconf):
    # regconf probably comes from walt.server.conf['registries'], ensure we will not
    # modify this configuration directly by performing a deep copy of the object
    regconf = deepcopy(regconf)
    # ready for the interactive screen
    print("Entering registries configuration editor... ", end="")
    sys.stdout.flush()
    time.sleep(2)
    if regconf is None:
        regconf = get_default_regconf()
    context = dict(
        initial_regconf=deepcopy(regconf),
        should_continue=True,
        return_value=None,
        menu_info_function=main_menu_info,
    )
    with alternate_screen_buffer():
        while True:
            pretty_print_regconf(regconf)
            valid = print_regconf_status(context, regconf)
            print()
            menu_info_function = context["menu_info_function"]
            menu_title, menu_options = menu_info_function(context, regconf, valid)
            selected = choose(menu_title, menu_options)
            action = selected[0]
            action_args = selected[1:]
            print()
            action(context, regconf, *action_args)
            if not context["should_continue"]:
                break
    print("\rEntering registries configuration editor... done")
    return regconf
