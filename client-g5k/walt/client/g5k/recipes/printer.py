from walt.client.g5k.recipes.tools import get_total_node_count
from walt.common.formatting import columnate, framed, highlight

CHECK_MARK = "\u2714"


def check_mark_or_empty(bool_value):
    if bool_value:
        return CHECK_MARK
    else:
        return ""


def printed_walltime(recipe_info):
    s = "G5K reservation walltime: "
    elems = []
    for n, unit in zip(
        (int(n) for n in recipe_info["walltime"].split(":")),
        ("hour", "minute", "second"),
    ):
        if n == 1:
            elems.append("1 " + unit)
        elif n > 1:
            elems.append("%d %ss" % (n, unit))
    if len(elems) == 3:
        s += elems[0] + ", " + elems[1] + " and " + elems[2]
    else:
        s += " and ".join(elems)
    return s


def printed_schedule(recipe_info):
    return (
        "G5K reservation schedule: "
        + {"night": "at night (or during week-end)", "asap": "as soon as possible"}[
            recipe_info["schedule"]
        ]
    )


def printed_deployment_info(recipe_info):
    server_site = recipe_info["server"]["site"]
    if server_site is None and get_total_node_count(recipe_info) == 0:
        return "Deployment info: " + highlight("none")
    header = ["site", "walt nodes", "walt server"]
    rows = []
    all_sites = set(recipe_info["node_counts"].keys())
    if server_site is not None:
        all_sites.add(server_site)
    for site in sorted(all_sites):
        has_server = site == server_site
        num_nodes = recipe_info["node_counts"].get(site, 0)
        if (num_nodes > 0) or has_server:
            rows.append([site, num_nodes, check_mark_or_empty(has_server)])
    return framed("Deployment info", columnate(rows, header)) + "\n"


def printed_current_recipe(recipe_info):
    recipe_desc = "\n".join(
        f(recipe_info)
        for f in (printed_deployment_info, printed_schedule, printed_walltime)
    )
    return framed("WalT deployment recipe", recipe_desc)


def print_recipe(recipe_info):
    print(printed_current_recipe(recipe_info))
