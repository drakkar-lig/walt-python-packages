import socket

from walt.common.config import load_conf

CONFIG_FILE_TOP_COMMENT = """\
WalT configuration file
***********************
This file was automatically generated.
You are allowed to edit the configuration values if needed.
However, instead of changing a value, you should consider removing the
related line instead. This would cause the walt client to prompt for this value
again, your new entry would pass an appropriate validity check, and this file
would be generated again accordingly.
"""

CONFIG_CODED_ITEMS = ("password",)

# This is not secure at all, we will just make passwords unreadable for someone spying
# your screen. The security is actually based on the access rights of the conf file
# (it is readable by the owner only).
# The docker framework relies on the same policy regarding password storage in
# .docker/conf.json or .dockercfg.
KEY = b"RAND0M STRING T0 HIDE A PASSW0RD"


def xor(password):
    key = (len(password) // len(KEY) + 1) * KEY  # repeat if KEY is too short
    return bytes(a ^ b for a, b in zip(key, password))


def ask_config_item(key, coded=False):
    msg = "%s: " % key
    while True:
        if coded:
            from getpass import getpass
            value = getpass(msg)
        else:
            value = input(msg)
        if value.strip() == "":
            continue
        break
    return value


def encode(value):
    return xor(value.encode("UTF-8")).hex()


def decode(coded_value):
    return xor(bytes.fromhex(coded_value)).decode("UTF-8")


def get_config_file():
    from os.path import expanduser
    from pathlib import Path
    p = Path(expanduser("~/.walt/config"))
    if not p.exists():
        legacy_p = Path(expanduser("~/.waltrc"))
        if legacy_p.exists():
            p.parent.mkdir(exist_ok=True)
            legacy_p.rename(p)
            p.chmod(0o600)
    return p


def ensure_group_path(conf_dict, *path):
    group_name, path = path[0], path[1:]
    if group_name not in conf_dict or not isinstance(conf_dict[group_name], dict):
        conf_dict[group_name] = {}
    if len(path) > 0:
        ensure_group_path(conf_dict[group_name], *path)


def cleanup_empty_groups(conf_dict):
    for item_type, item_path, parent_group, item_name, item_value in reversed(
        list(iter_conf_items(conf_dict, iter_groups=False))
    ):
        if item_type == "group" and len(item_value) == 0:
            parent_group.pop(item_name)


def get_config_from_file():
    config_file = get_config_file()
    try:
        conf_dict = load_conf(config_file, optional=True, fast_load_mode=True)
        if conf_dict is None:
            return {}, False
    except Exception:
        print(
            f"Warning: {config_file} file exists, but it could not be parsed properly."
        )
        return {}, False
    # handle legacy conf items
    updated = False
    ensure_group_path(conf_dict, "walt")
    ensure_group_path(conf_dict, "registries")
    if "hub" in conf_dict:
        conf_dict["registries"]["hub"] = conf_dict.pop("hub")
        updated = True
    ensure_group_path(conf_dict, "registries", "hub")
    if "server" in conf_dict:
        conf_dict["walt"]["server"] = conf_dict.pop("server")
        updated = True
    if "username" in conf_dict:
        conf_dict["walt"]["username"] = conf_dict.pop("username")
        # walt and hub usernames were previously always the same
        conf_dict["registries"]["hub"]["username"] = conf_dict["walt"]["username"]
        updated = True
    if "password" in conf_dict:
        conf_dict["registries"]["hub"]["password"] = conf_dict.pop("password")
        updated = True
    cleanup_empty_groups(conf_dict)
    # decode coded items
    for item_type, item_path, parent_group, item_name, item_value in iter_conf_items(
        conf_dict, iter_groups=False
    ):
        if item_name in CONFIG_CODED_ITEMS:
            parent_group[item_name] = decode(parent_group[item_name])
    return conf_dict, updated


def iter_conf_items(conf_dict, path=(), iter_leaves=True, iter_groups=True):
    for item_name, item_conf in conf_dict.items():
        new_path = path + (item_name,)
        if isinstance(item_conf, dict):
            if iter_groups:
                yield "group", new_path, conf_dict, item_name, item_conf
            yield from iter_conf_items(item_conf, new_path)
        else:
            if iter_leaves:
                yield "leaf", new_path, conf_dict, item_name, item_conf


class ConfigFileSaver:
    def __init__(self):
        self.item_groups = []
        self.static_comments = {
            ("walt",): "WalT platform",
            ("walt", "server"): "IP or hostname of WalT server",
            ("walt", "username"): "WalT user name used to identify your work",
            ("registries",): "Credentials for container registries",
        }

    def get_comment(self, path):
        if path in self.static_comments:
            return self.static_comments[path]
        if len(path) == 2 and path[0] == "registries":
            if path[1] == "hub":
                return "Docker Hub credentials"
            else:
                return f'Credentials for registry "{path[1]}"'

    def save(self):
        # concatenate all and write the file
        config_file = get_config_file()
        config_file.parent.mkdir(exist_ok=True)
        config_file.write_text(self.printed())
        config_file.chmod(0o600)
        print("\nConfiguration was updated in %s.\n" % config_file)

    def comment_section(self, lines, section, indent=0):
        return lines.extend(
            self.indent_lines(self.comment_lines(section.splitlines()), indent)
        )

    def comment_lines(self, lines):
        return ["# " + line for line in lines]

    def indent_lines(self, lines, indent):
        return [(" " * indent) + line for line in lines]

    def underline(self, line):
        import re
        dashes = re.sub(".", "-", line)
        return f"{line}\n{dashes}"

    def printed(self):
        import yaml
        lines = [""]
        self.comment_section(lines, CONFIG_FILE_TOP_COMMENT)
        lines.append("")
        for (
            item_type,
            item_path,
            parent_group,
            item_name,
            item_value,
        ) in iter_conf_items(conf_dict):
            comment = self.get_comment(item_path)
            indent = (len(item_path) - 1) * 4
            if item_type == "group":
                # add group-level comment
                if comment is not None:
                    if indent == 0:
                        lines.append("")
                        comment = self.underline(comment)
                    self.comment_section(lines, comment, indent)
                # add group name
                lines.append(f'{" "*indent}{item_name}:')
            else:
                # add leaves
                if item_name in CONFIG_CODED_ITEMS:
                    new_comment = "(%s value is encoded.)" % item_name
                    comment = (
                        new_comment if comment is None else f"{comment} {new_comment}"
                    )
                    item_value = encode(item_value)
                if comment is not None:
                    self.comment_section(lines, comment, indent)
                # get yaml output for this item only
                # (by creating a temporary dictionary with just this item)
                item_and_value = yaml.dump({item_name: item_value}).strip()
                lines.append(f'{" "*indent}{item_and_value}')
        return "\n".join(lines) + "\n\n"


def save_config():
    saver = ConfigFileSaver()
    saver.save()


def set_conf(in_conf):
    global conf_dict
    conf_dict = in_conf


def reload_conf():
    conf_dict, should_rewrite = get_config_from_file()
    set_conf(conf_dict)
    if should_rewrite:
        save_config()


def resolve_new_user():
    server_check = "server" not in conf_dict["walt"]
    if server_check:
        from walt.client.plugins import get_hook
        hook = get_hook("config_missing_server")
        if hook is not None:
            server_check = hook()
    print(
        "You are a new user of this WalT platform, "
        + "and this command requires a few configuration items."
    )
    use_hub = False
    while True:
        server_update = "server" not in conf_dict["walt"]
        username_update = "username" not in conf_dict["walt"]
        if server_update:
            conf_dict["walt"]["server"] = ask_config_item(
                "IP or hostname of WalT server"
            )
        if username_update:
            from walt.client.tools import yes_or_no
            use_hub = yes_or_no(
                "Do you intend to push or pull images to/from the docker hub?",
                okmsg=None,
                komsg=None,
            )
            if use_hub:
                ensure_group_path(conf_dict, "registries", "hub")
                print(
                    "Please get an account at hub.docker.com if not done yet, "
                    + "then specify credentials here."
                )
                conf_dict["registries"]["hub"].update(
                    username=ask_config_item("username"),
                    password=ask_config_item("password", coded=True),
                )
                conf_dict["walt"]["username"] = conf_dict["registries"]["hub"][
                    "username"
                ]
            else:
                conf_dict["walt"]["username"] = ask_config_item(
                    "Please choose a username for this walt platform"
                )
        test_registry_name = "hub" if use_hub else None
        server_error, registry_error = test_config(test_registry_name)
        if not any((server_error, registry_error)):
            break  # OK done
        if registry_error:
            # walt username was copied from hub username, but hub credentials are wrong
            # so forget it
            del conf_dict["walt"]["username"]
        continue  # prompt again to user
    if use_hub:
        username = conf_dict["walt"]["username"]
        print(f"Note: {username} will also be your username on the WalT platform.")


def resolve_registry_creds(reg_name):
    if reg_name == "hub":
        creds_name = "Docker hub credentials"
    else:
        creds_name = f'Credentials for access to "{reg_name}" registry'
    print(f"{creds_name} are missing or invalid. Please enter them below.")
    ensure_group_path(conf_dict, "registries", reg_name)
    while True:
        conf_dict["registries"][reg_name].update(
            username=ask_config_item("username"),
            password=ask_config_item("password", coded=True),
        )
        errors = test_config(reg_name)
        if not any(errors):
            break


class ConfSpecNode:
    pass


class ConfSpecRegistryNode:
    def __init__(self, reg_name):
        self.username = ConfSpecNode()
        self.username.resolve = lambda: resolve_registry_creds(reg_name)
        self.password = ConfSpecNode()
        self.password.resolve = lambda: resolve_registry_creds(reg_name)


class ConfSpecRegistriesNode:
    def __getattr__(self, reg_name):
        if reg_name == "resolve":
            raise AttributeError
        setattr(self, reg_name, ConfSpecRegistryNode(reg_name))
        return self.reg_name


ConfSpec = ConfSpecNode()
ConfSpec.walt = ConfSpecNode()
ConfSpec.walt.server = ConfSpecNode()
ConfSpec.walt.server.resolve = resolve_new_user
ConfSpec.walt.username = ConfSpecNode()
ConfSpec.walt.username.resolve = resolve_new_user
ConfSpec.registries = ConfSpecRegistriesNode()


def init_config(link_cls):
    global server_link_cls
    server_link_cls = link_cls


def test_config(registry_name=None):
    # we try to establish a connection to the server,
    # and optionaly to connect to the docker hub.
    # the return value is a tuple of 2 elements telling
    # whether a server connection or a hub credentials error
    # occured.
    print()
    print("Testing provided configuration...")
    if server_link_cls is None:
        raise Exception("test_config() called but server_link_cls not known yet.")
    try:
        with server_link_cls() as server:
            if registry_name is not None:
                with server.set_busy_label("Authenticating to the registry"):
                    if not server.registry_login(registry_name):
                        print()
                        del conf_dict["registries"][registry_name]["username"]
                        del conf_dict["registries"][registry_name]["password"]
                        return False, True
    except socket.error:
        print(
            "FAILED. The value of 'walt.server' you entered seems invalid "
            + "(or the server is down?)."
        )
        print()
        del conf_dict["walt"]["server"]
        return True, False
    print("OK.")
    print()
    return False, False


server_link_cls = None
conf_dict = None


class Conf:
    def __init__(self, path=()):
        self._path = path

    def __repr__(self):
        return "<Configuration: " + repr(self._analyse_path(self._path)) + ">"

    def _do_lazyload(self):
        if conf_dict is None:
            reload_conf()

    def _analyse_path(self, path):
        self._do_lazyload()
        conf_spec, conf_obj, cur_path = ConfSpec, conf_dict, ()
        for attr in path:
            cur_path += (attr,)
            conf_spec = getattr(conf_spec, attr, None)
            if conf_spec is None:
                conf_item_str = "conf." + ".".join(cur_path)
                raise Exception(f"Unexpected conf item: {conf_item_str}")
            if hasattr(conf_spec, "resolve"):
                # leaf value
                if attr in conf_obj:
                    return {"type": "present-leaf", "value": conf_obj[attr]}
                else:

                    def resolve():
                        conf_spec.resolve()
                        save_config()

                    return {"type": "missing-leaf", "resolve": resolve}
            else:
                # category node
                if attr not in conf_obj:
                    conf_obj[attr] = {}
            conf_obj = conf_obj[attr]
        return {"type": "category", "value": conf_obj}

    # we use point-based notation (e.g., conf.walt.server)
    def __getattr__(self, attr):
        path = self._path + (attr,)
        path_info = self._analyse_path(path)
        if path_info["type"] == "present-leaf":
            return path_info["value"]
        elif path_info["type"] == "missing-leaf":
            path_info["resolve"]()
            return self.__getattr__(attr)  # redo
        else:  # category
            return Conf(path)

    def __hasattr__(self, attr):
        path = self._path + (attr,)
        path_info = self._analyse_path(path)
        return path_info["type"] != "missing-leaf"

    def __setattr__(self, attr, v):
        if attr in ("_path",):
            self.__dict__[attr] = v
            return
        cat_path_info = self._analyse_path(self._path)
        item_path_info = self._analyse_path(self._path + (attr,))
        assert cat_path_info["type"] == "category"
        assert item_path_info["type"] in ("present-leaf", "missing-leaf")
        cat_path_info["value"][attr] = v


conf = Conf()
