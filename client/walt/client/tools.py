import sys


def yes_or_no(msg, okmsg="OK.\n", komsg="OK.\n"):
    while True:
        print("%s (y/n):" % msg, end=" ")
        res = input()
        if res == "y":
            if okmsg:
                print(okmsg)
            return True
        elif res == "n":
            if komsg:
                print(komsg)
            return False
        else:
            print("Invalid response.")


def choose(msg="possible values:", **args):
    while True:
        print(msg)
        for k, explain in args.items():
            print("* %s: %s" % (k, explain))
        all_keys = "/".join(args.keys())
        print("selected value (%s):" % all_keys, end=" ")
        res = input()
        if res in args:
            return res
        else:
            print("Invalid response.\n")


def confirm(msg="Are you sure?", komsg="Aborted."):
    return yes_or_no(msg, komsg=komsg)


def check_nodes_ownership(
    server, node_set, mode="owned-or-free", ignore_other_devices=False
):
    from walt.common.formatting import format_sentence

    owned, free, not_owned, not_nodes = server.filter_ownership(node_set)
    if len(owned) + len(free) + len(not_owned) + len(not_nodes) == 0:
        return False  # error during api call, already reported
    if not ignore_other_devices and len(not_nodes) > 0:
        sys.stderr.write(
            format_sentence(
                "Error: %s is(are) not a() WalT node(nodes).",
                not_nodes,
                "",
                "Device",
                "Devices",
            ).replace('  ', ' ')
            + " Aborting.\n"
        )
        return False
    if mode == "free-or-not-owned" and len(owned) > 0:
        sys.stderr.write(
            format_sentence(
                (
                    "Error: %s is(are) already yours."
                    " See `walt help show node-ownership`."
                ),
                owned,
                "",
                "Node",
                "Nodes",
            )
            + "\n"
        )
        return False
    if mode == "owned" and len(free) + len(not_owned) > 0:
        sys.stderr.write(
            format_sentence(
                "Error: %s is(are) not yours. See `walt help show node-ownership`.",
                free + not_owned,
                "",
                "Node",
                "Nodes",
            )
            + "\n"
        )
        return False
    if mode in ("owned-or-free", "free-or-not-owned") and len(not_owned) > 0:
        sys.stderr.write(
            format_sentence(
                "Warning: %s seems(seem) to be used by another(other) user(users).",
                not_owned,
                "",
                "Node",
                "Nodes",
            )
            + "\n"
        )
        if not confirm():
            return False
    return True
