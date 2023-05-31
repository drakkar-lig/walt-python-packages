import copy
import json
import os
import re
import sys
import textwrap
from pathlib import Path

import yaml
from walt.server.config import cleanup_defaults
from walt.server.setup.netconf import (
    edit_netconf_interactive,
    get_default_netconf,
    get_netconf_entry_comments,
    sanitize_netconf,
)
from walt.server.setup.regconf import edit_regconf_interactive, get_default_regconf

YAML_INDENT = 4


def category_comment(s):
    return "\n" + s + "\n" + (len(s) * "-")


WALT_SERVER_CONF = {
    "PATH": Path("/etc/walt/server.conf"),
    "HEADER_COMMENT": """
# WalT server configuration file.
# Run 'walt-server-setup --edit-conf' to update.
""",
    "COMMENT_INFO": {
        (0, "network:"): category_comment("network configuration"),
        (0, "registries:"): category_comment("image registries"),
        (0, "services:"): category_comment("service files"),
    },
}

CONTAINERS_REGISTRIES_CONF = {
    "PATH": Path("/etc/containers/registries.conf.d/walt.conf"),
    "HEADER_COMMENT": """
# Image registries configuration for this WALT server.
# Run 'walt-server-setup --edit-conf' to update.""",
}

WALT_SERVER_SPEC_PATH = Path("/etc/walt/server.spec")
WALT_SERVER_SPEC_CONTENT = """\
{
    # optional features implemented
    # -----------------------------
    "features": [ "ptp" ]
}
"""

ROOT_LEGACY_WALTRC_PATH = Path("/root/.waltrc")
ROOT_WALT_CONFIG_PATH = Path("/root/.walt/config")
SKEL_WALT_CONFIG_PATH = Path("/etc/skel/.walt/config")
LOCAL_WALT_CONFIG_CONTENT = """\
# WalT configuration file
# ***********************

# WalT platform
# -------------
walt:
    # IP or hostname of WalT server
    server: localhost
"""


def get_current_conf():
    try:
        from walt.server import conf

        return conf
    except Exception:
        return None


def edit_conf_tty_error():
    print(
        "Sorry, cannot run server configuration editor because STDOUT is not a"
        " terminal."
    )
    print("Exiting.")
    sys.exit(1)


def edit_conf_keep():
    conf = get_current_conf()
    if conf is None:
        print("WARNING: Failed to load current configuration at /etc/walt/server.conf!")
        print("WARNING: Falling back to a default configuration.")
        conf = edit_conf_set_default()
    return conf


def edit_conf_set_default():
    # verify we will not overwrite an existing conf
    conf = get_current_conf()
    if conf is None:
        # this was actually expected
        return {"network": get_default_netconf(), "registries": get_default_regconf()}
    else:
        print("Note: found valid yaml file at /etc/walt/server.conf, keeping it.")
        return conf


def edit_conf_interactive():
    conf = get_current_conf()
    if conf is None:
        conf = edit_conf_set_default()
    else:
        conf = copy.deepcopy(conf)  # copy
    netconf, regconf = conf["network"], conf["registries"]
    conf["network"] = edit_netconf_interactive(netconf)
    conf["registries"] = edit_regconf_interactive(regconf)
    return conf


def define_server_conf(mode, opt_edit_conf):
    selector = (os.isatty(1), mode, opt_edit_conf)
    edit_conf_mode = {
        (True, "image-install", True): "interactive",
        (True, "install", True): "interactive",
        (True, "upgrade", True): "interactive",
        (True, "image-install", False): "set_default",
        (True, "install", False): "interactive",
        (True, "upgrade", False): "keep",
        (False, "image-install", True): "tty_error",
        (False, "install", True): "tty_error",
        (False, "upgrade", True): "tty_error",
        (False, "image-install", False): "set_default",
        (False, "install", False): "set_default",
        (False, "upgrade", False): "keep",
    }[selector]
    func = globals().get(f"edit_conf_{edit_conf_mode}")
    return func()


def same_confs(c1, c2):
    if c1 is None or c2 is None or "network" not in c1 or "network" not in c2:
        return False
    sanitize_netconf(c1["network"])
    sanitize_netconf(c2["network"])
    return c1 == c2


def dump_commented_conf(conf, comment_info):
    reordered_conf = {}
    for k in ["network", "registries", "services"]:
        if k in conf:
            reordered_conf[k] = conf.pop(k)
    conf.update(reordered_conf)
    conf_dump = yaml.dump(conf, indent=YAML_INDENT, sort_keys=False)

    # add comments
    def add_desc_comment(match):
        indent, pattern = match.groups()
        depth = len(indent) / YAML_INDENT
        comment = comment_info.get((depth, pattern), None)
        if comment is None:
            lines = []
        else:
            lines = [
                (f"# {line}" if len(line) > 0 else line)
                for line in comment.splitlines()
            ]
        lines += [pattern]
        return "\n".join(f"{indent}{line}" for line in lines)

    conf_dump = re.sub(
        r"^([ \t]*)([^\n]*)", add_desc_comment, conf_dump, flags=re.MULTILINE
    )
    return WALT_SERVER_CONF["HEADER_COMMENT"] + conf_dump + "\n"


def dump_containers_registries_conf(regconf):
    containers_registries = []
    for reg in regconf:
        if reg["api"] == "docker-hub":
            containers_registries.append(
                dict(
                    prefix="docker.io", location="registry-1.docker.io", insecure=False
                )
            )
        else:
            location = f'{reg["host"]}:{reg["port"]}'
            insecure = reg["protocol"] != "https"  # 'http' or 'https-no-verify'
            containers_registries.append(
                dict(prefix=location, location=location, insecure=insecure)
            )
    header = CONTAINERS_REGISTRIES_CONF["HEADER_COMMENT"]
    seach_list_text = "unqualified-search-registries = " + json.dumps(
        list(reg["prefix"] for reg in containers_registries)
    )
    reg_sections_text = textwrap.dedent(
        "\n\n".join(
            f"""\
            [[registry]]
            prefix = "{reg['prefix']}"
            location = "{reg['location']}"
            insecure = {json.dumps(reg['insecure'])}""" for reg in containers_registries
        )
    )
    return "\n\n".join((header, seach_list_text, reg_sections_text)) + "\n"


def update_server_conf(conf):
    same_conf = same_confs(get_current_conf(), conf)
    if not same_conf:
        print(f'Saving configuration at {WALT_SERVER_CONF["PATH"]}... ', end="")
        conf = cleanup_defaults(conf)
        comment_info = dict(WALT_SERVER_CONF["COMMENT_INFO"])
        netconf = conf["network"]
        netconf_entry_comments = get_netconf_entry_comments(netconf)
        comment_info.update({(1, k): v for (k, v) in netconf_entry_comments.items()})
        conf_text = dump_commented_conf(conf, comment_info)
        WALT_SERVER_CONF["PATH"].parent.mkdir(parents=True, exist_ok=True)
        WALT_SERVER_CONF["PATH"].write_text(conf_text)
        print("done")
    if not same_conf or not CONTAINERS_REGISTRIES_CONF["PATH"].exists():
        print(
            (
                "Saving registries configuration at"
                f" {CONTAINERS_REGISTRIES_CONF['PATH']}... "
            ),
            end="",
        )
        registries_text = dump_containers_registries_conf(conf["registries"])
        CONTAINERS_REGISTRIES_CONF["PATH"].parent.mkdir(parents=True, exist_ok=True)
        CONTAINERS_REGISTRIES_CONF["PATH"].write_text(registries_text)
        print("done")


def fix_other_conf_files():
    if not ROOT_WALT_CONFIG_PATH.exists() and ROOT_LEGACY_WALTRC_PATH.exists():
        print(
            f"Moving legacy {ROOT_LEGACY_WALTRC_PATH} -> {ROOT_WALT_CONFIG_PATH}... ",
            end="",
        )
        sys.stdout.flush()
        ROOT_WALT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        ROOT_LEGACY_WALTRC_PATH.rename(str(ROOT_WALT_CONFIG_PATH))
        print("done")
    for path, content in (
        (WALT_SERVER_SPEC_PATH, WALT_SERVER_SPEC_CONTENT),
        (ROOT_WALT_CONFIG_PATH, LOCAL_WALT_CONFIG_CONTENT),
        (SKEL_WALT_CONFIG_PATH, LOCAL_WALT_CONFIG_CONTENT),
    ):
        if not path.exists():
            print(f"Writing {path}... ", end="")
            sys.stdout.flush()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            print("done")
