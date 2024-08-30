import numpy as np
from time import time

from walt.server.processes.main.workflow import Workflow


def complete_node(server, username):
    return server.nodes.show(username, show_all=True, names_only=True).split()


def complete_device(server, partial_token):
    return tuple(
        dev.name
        for dev in server.db.select("devices")
        if dev.name.startswith(partial_token)
    )


def complete_switch(server, partial_token):
    return tuple(
        dev.name
        for dev in server.db.select("devices", type="switch")
        if dev.name.startswith(partial_token)
    )


def complete_set(possible_items, partial_token):
    set_items = partial_token.split(",")
    partial_item = set_items[-1]
    prefix = "".join(item + "," for item in set_items[:-1])
    possible = tuple(
        prefix + item for item in possible_items if item.startswith(partial_item)
    )
    # if only one possible match, propose this match or this match plus a comma
    if len(possible) == 1:
        possible = (possible[0], possible[0] + ",")
    return possible


def complete_set_of_nodes(server, username, partial_token):
    all_nodes = complete_node(server, username)
    keywords = ["my-nodes", "all-nodes", "free-nodes"]
    return complete_set(all_nodes + keywords, partial_token)


def complete_set_of_devices(server, partial_token):
    all_devices = list(dev.name for dev in server.db.select("devices"))
    keywords = [
        "all-devices",
        "all-switches",
        "explorable-switches",
        "my-nodes",
        "all-nodes",
        "free-nodes",
    ]
    return complete_set(all_devices + keywords, partial_token)


def complete_set_of_emitters(server, partial_token):
    all_allowed_devices = list(
        dev.name
        for dev in server.db.select("devices")
        if dev.name.startswith(partial_token) and dev.type in ("node", "server")
    )
    keywords = ["my-nodes", "all-nodes", "free-nodes", "server"]
    return complete_set(all_allowed_devices + keywords, partial_token)


def complete_rescan_set_of_devices(server, partial_token):
    # allow to complete a switch which has lldp exploration forbidden,
    # so that the user can try and get the informative error message.
    all_switches = list(
        dev.name for dev in server.db.select("devices") if dev.type == "switch"
    )
    keywords = ["explorable-switches", "server"]
    return complete_set(all_switches + keywords, partial_token)


def complete_image(server, requester, username):
    rows = server.images.get_user_tabular_data(
        requester, username, refresh=False, fields=["name"]
    )
    names = tuple(row[0] for row in rows)
    implicit_names = tuple(f"{name}:latest" for name in names if ":" not in name)
    return names + implicit_names


def wf_fs_remote_completions(wf, server, requester,
        entity_type, entity, partial_token, possible, **env):
    # '<entity>:<remote-path>' pattern
    # we need to complete the remote path
    # caution: images may have a tag, i.e. pattern is '<name>:<tag>:<remote-path>'
    partial_remote_path = partial_token[len(entity) + 1 :]
    # when typing walt image cp teleworker:test:/<tab>, we will not bother
    # exploring a possible 'teleworker' image (with its implicit ':latest' tag)
    # looking for files starting with 'test:/'...
    if ":" in partial_remote_path:
        wf.next()   # nothing more to add to "possible" list
        return
    fs = None
    if entity_type == "node":
        fs = server.nodes.get_node_filesystem(requester, entity)
    elif entity_type == "image":
        fs = server.images.get_image_filesystem(requester, entity)
    if fs is not None:
        # if previous completion attempt to the same [node|image] did
        # not complete, abort it to be able to run this one.
        if fs.busy():
            fs.full_close()
        wf.update_env(filesystem=fs, partial_path=partial_remote_path)
        wf.insert_steps([fs.wf_ping, wf_fs_after_ping])
    wf.next()


def wf_fs_after_ping(wf, alive, filesystem, **env):
    if alive:
        wf.insert_steps([filesystem.wf_get_completions,
                         wf_after_get_completions])
    wf.next()


def wf_after_get_completions(wf, entity, possible, remote_completions, **env):
    possible.extend(f"{entity}:{path}" for path in remote_completions)
    wf.next()


def get_cp_entities(server, requester, username, entity_type):
    if entity_type == "node":
        return complete_node(server, username)
    elif entity_type == "image":
        return complete_image(server, requester, username)


def wf_complete_cp_src(wf, server, requester, username,
        entity_type, partial_token, **env):
    possible = []
    if ":" not in partial_token:
        possible += list(requester.filesystem.get_completions(partial_token))
    possible_entities = get_cp_entities(server, requester, username, entity_type)
    for entity in possible_entities:
        if partial_token.startswith(f"{entity}:"):
            wf.update_env(entity=entity)
            wf.insert_steps([wf_fs_remote_completions])
        elif entity.startswith(partial_token):
            possible += [f"{entity}:"]
    wf.update_env(possible=possible)
    wf.next()


def wf_complete_cp_dst(wf, server, requester, username,
        entity_type, src_token, partial_dst_token, **env):
    possible = []
    src_is_remote = ":" in src_token
    dst_is_remote = not src_is_remote
    if dst_is_remote:
        possible_entities = get_cp_entities(server, requester, username, entity_type)
        for entity in possible_entities:
            if partial_dst_token.startswith(f"{entity}:"):
                wf.update_env(entity=entity, partial_token=partial_dst_token)
                wf.insert_steps([wf_fs_remote_completions])
            elif entity.startswith(partial_dst_token):
                possible += [f"{entity}:"]
    else:
        possible += list(requester.filesystem.get_completions(partial_dst_token))
        possible += ["booted-image"]
    wf.update_env(possible=possible)
    wf.next()


def complete_device_config_param(server, requester, argv):
    partial_token, prev_args = argv[-1], argv[:-1]
    # we will just help the user with the setting names, not the values
    if "=" in partial_token:
        return ()
    # find the device_set by scanning argv backwards
    device_set = None
    for arg in reversed(prev_args):
        if "=" not in arg:
            device_set = arg
            break
    if device_set is None:
        return None
    # get config data
    config_data = server.settings.get_device_config_data(requester, device_set)
    if config_data is None or len(config_data) == 0:
        return None
    # we are only interested in the setting names, not values,
    # so convert setting dicts to sets.
    setting_names_sets = np.vectorize(set)(config_data.settings)
    # we will propose only settings that can be applied to all
    # specified devices, so aggregate these sets by using a
    # set intersection operation.
    setting_names = np.bitwise_and.reduce(setting_names_sets)
    # match only those which start with partial_token
    return tuple(f"{name}=" for name in setting_names
                     if name.startswith(partial_token))


def complete_port_config_param(server, partial_token):
    # we will just help the user with the setting names, not the values
    if "=" in partial_token:
        return ()
    return tuple(f"{name}=" for name in
                 server.port_settings.get_writable_setting_names())


def get_walt_clone_urls(server, username):
    # faster than using server.registry
    return tuple(
        f"walt:{img.fullname}"
        for img in server.db.select("images")
        if not img.fullname.startswith(f"{username}/")
    )


def complete_image_clone_url(server, username, partial_token):
    # note: we might implement completion of docker daemon images without blocking
    # this main process by refactoring this completion code:
    # - setting the current main task to 'async'
    # - delegate the gathering of this list to the blocking process.
    if partial_token.startswith("walt:"):
        return get_walt_clone_urls(server, username)
    # fetching from other locations would be probably too long for autocompletion,
    # user has to use "walt image search" instead
    from walt.server.tools import get_clone_url_locations

    return get_clone_url_locations()


def complete_log_checkpoint(server, username):
    return tuple(cp.name for cp in server.db.select("checkpoints", username=username))


def complete_history_range(server, username, partial_token):
    checkpoints = complete_log_checkpoint(server, username)
    if ":" in partial_token:
        start, end = partial_token.split(":", maxsplit=1)
        if end.startswith("-"):
            return ()  # let the user input the relative date
        else:
            possible_end_bound = ("-<relative-time>", "") + checkpoints
            return tuple(f"{start}:{p_end}" for p_end in possible_end_bound)
    else:
        start = partial_token
        if start.startswith("-"):
            return ()  # let the user input the relative date
        else:
            possible_start_bound = ("full", "none", "-<relative-time>:", ":") + tuple(
                f"{cp}:" for cp in checkpoints
            )
            return possible_start_bound


def complete_image_registry(partial_token):
    from walt.server.tools import get_registry_labels

    return get_registry_labels() + ("auto",)


def wf_shell_autocomplete_switch(wf, task, server, requester, username, argv, **env):
    arg_type = argv[0]
    partial_token = argv[-1]
    if arg_type in ("NODE_CP_SRC", "NODE_CP_DST", "IMAGE_CP_SRC", "IMAGE_CP_DST"):
        entity_type, _, src_or_dst = arg_type.lower().split("_")
        if src_or_dst == "src":
            wf.update_env(
                entity_type=entity_type,
                partial_token=partial_token)
            wf.insert_steps([wf_complete_cp_src])
        else:
            prev_token = argv[-2]
            wf.update_env(
                entity_type=entity_type,
                src_token=prev_token,
                partial_dst_token=partial_token)
            wf.insert_steps([wf_complete_cp_dst])
        wf.next()
    else:
        if arg_type == "NODE":
            possible = complete_node(server, username)
        elif arg_type == "SET_OF_NODES":
            possible = complete_set_of_nodes(server, username, partial_token)
        elif arg_type == "IMAGE":
            possible = complete_image(server, requester, username)
        elif arg_type == "IMAGE_OR_DEFAULT":
            possible = ("default",) + complete_image(server, requester, username)
        elif arg_type == "NODE_CONFIG_PARAM":
            possible = complete_device_config_param(server, requester, argv)
        elif arg_type == "DEVICE":
            possible = complete_device(server, partial_token)
        elif arg_type == "SWITCH":
            possible = complete_switch(server, partial_token)
        elif arg_type == "SET_OF_DEVICES":
            possible = complete_set_of_devices(server, partial_token)
        elif arg_type == "RESCAN_SET_OF_DEVICES":
            possible = complete_rescan_set_of_devices(server, partial_token)
        elif arg_type == "DEVICE_CONFIG_PARAM":
            possible = complete_device_config_param(server, requester, argv)
        elif arg_type == "PORT_CONFIG_PARAM":
            possible = complete_port_config_param(server, partial_token)
        elif arg_type == "IMAGE_CLONE_URL":
            possible = complete_image_clone_url(server, username, partial_token)
        elif arg_type == "LOG_CHECKPOINT":
            possible = complete_log_checkpoint(server, username)
        elif arg_type == "HISTORY_RANGE":
            possible = complete_history_range(server, username, partial_token)
        elif arg_type == "SET_OF_ISSUERS":
            possible = complete_set_of_emitters(server, partial_token)
        elif arg_type == "REGISTRY":
            possible = complete_image_registry(partial_token)
        else:
            possible = ()
        wf.update_env(possible=possible)
        wf.next()


# in some cases, we want to prevent bash to print a trailing space
# when a single completion match is returned. instead, we want the
# user to hit <tab> again to further complete the token.
# in such a case, we use the following trick.
def mark_incomplete(token):
    return (f"{token}a", f"{token}b")


def wf_shell_autocomplete(wf, task, debug, **env):
    # autocompletion should not print failure messages
    wf.insert_steps([wf_shell_autocomplete_switch])
    try:
        wf.next()
    except Exception:
        if debug:
            raise
        wf.interrupt()
        task.return_result("")


def wf_filter_possible(wf, argv, possible, **env):
    arg_type = argv[0]
    partial_token = argv[-1]
    possible = tuple(item for item in possible if item.startswith(partial_token))
    # if only one possible match...
    if len(possible) == 1:
        item = possible[0]
        # ...and we are juste adding a useless ':latest' default tag
        # to the image name...
        if (
            arg_type in ("IMAGE_CP_SRC", "IMAGE_CP_DST")
            and partial_token.endswith(":")
            and item == f"{partial_token}latest:"
        ):
            return ""  # forget this useless proposal
        # ...if single match is ending with a field separation char...
        if item[-1] in ("/", ":", "="):
            # ...then we want to prevent bash to print a trailing space
            # validating this single match...
            if item == partial_token:
                # so if we could not complete more, return ''
                return ""
            else:
                # and if we could complete more, use our special trick
                possible = mark_incomplete(item)
    elif len(possible) == 2:
        # if 2nd possible image is <1st>:latest, keep <1st> only
        if (
            arg_type in ("IMAGE", "IMAGE_OR_DEFAULT")
            and possible[1] == f"{possible[0]}:latest"
        ):
            possible = (possible[0],)
    wf.update_env(possible=possible)
    wf.next()


def wf_return_result(wf, task, possible, debug, t0=None, **env):
    result = " ".join(possible)
    if debug:
        print(f"{time()-t0:.2}s -- returning: {result}")
    task.return_result(result)
    wf.next()


def shell_autocomplete(server, task, requester, username, argv, debug=False):
    env=dict(
        server=server,
        task=task,
        requester=requester,
        username=username,
        argv=argv,
        debug=debug,
    )
    if debug:
        env.update(t0=time())
    task.set_async()
    wf = Workflow([wf_shell_autocomplete,
                   wf_filter_possible,
                   wf_return_result],
                   **env
    )
    wf.run()
