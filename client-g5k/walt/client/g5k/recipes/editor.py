import sys
from datetime import datetime

from plumbum.cli.terminal import prompt
from walt.client.g5k.recipes.const import SCHEDULE_DESC
from walt.client.g5k.recipes.printer import print_recipe
from walt.client.g5k.recipes.tools import get_total_node_count
from walt.client.g5k.reservation import (
    analyse_reservation,
    get_g5k_sites,
    get_g5k_sites_for_walt_server,
)
from walt.common.formatting import highlight
from walt.common.term import alternate_screen_buffer, choose, clear_screen

sites = sorted(["grenoble", "lille", "nancy", "luxembourg"])


def human_readable_time(ts):
    now = datetime.now()
    start = datetime.fromtimestamp(ts)
    delay_seconds = (start - now).seconds
    delay_days = (start.date() - now.date()).days
    if delay_seconds < 10 * 60:
        return "In a few minutes"
    if delay_days == 0:
        return "Today at " + start.strftime("%X")
    if delay_days == 1:
        return "Tomorrow at " + start.strftime("%X")
    return start.strftime("%c")


def print_recipe_status(context, recipe_info):
    s = "Recipe status: "
    undefined = []
    if recipe_info["server"]["site"] is None:
        undefined.append("WalT server site")
    if get_total_node_count(recipe_info) == 0:
        undefined.append("WalT nodes")
    if len(undefined) > 0:
        print(s + highlight("invalid") + " (tip: define " + ", ".join(undefined) + ")")
        return False  # invalid
    print()
    if context["start_time_estimation"]:
        busy_message = "Analysing... "
        sys.stdout.write(busy_message)
        sys.stdout.flush()
        valid, res_info = analyse_reservation(recipe_info)
        sys.stdout.write("\r" + " " * len(busy_message) + "\r")
        sys.stdout.flush()
        if valid:
            startup = res_info["selected_slot"]["start"]
            print(s + "OK")
            print("Estimated reservation start:", human_readable_time(startup))
        else:
            print(s + highlight("not available") + " (tip: " + res_info["tip"] + ")")
    else:
        valid = True
        print(s + "OK")
        print("Estimated reservation start: <not-computed>")
    return valid


def define_walt_server(context, recipe_info):
    site = choose(
        "On which site should WalT server run?", get_g5k_sites_for_walt_server()
    )
    recipe_info["server"]["site"] = site


def change_walt_nodes(context, recipe_info):
    site = choose("On which site should WalT nodes be defined?", get_g5k_sites())
    number = prompt(
        "Define how many WalT nodes should run there",
        type=int,
        validator=lambda x: x >= 0,
    )
    if number > 0:
        recipe_info["node_counts"][site] = number
    else:
        # 0 nodes, remove the site from "node_counts"
        recipe_info["node_counts"].pop(site, None)


def validate_walltime(wt):
    valid = True
    try:
        elems = tuple(int(e) for e in wt.split(":"))
        elems += (0,) * (3 - len(elems))
        hours, minutes, seconds = elems
        if hours < 0 or minutes < 0 or seconds < 0:
            valid = False
        elif minutes > 59 or seconds > 59:
            valid = False
        elif elems == (0, 0, 0):
            valid = False
    except Exception:
        valid = False
    if not valid:
        print(
            "Expected format is the one of oarsub command (e.g. 01:00:00 for one hour)."
        )
    return valid


def change_walltime(context, recipe_info):
    print(
        "G5K reservation walltime defines the lifetime of your temporary WalT platform."
    )
    recipe_info["walltime"] = prompt(
        "Please enter it (oarsub format, e.g. 01:00:00)", validator=validate_walltime
    )


def change_schedule(context, recipe_info):
    print("G5K reservation schedule defines the time when deployment will start.")
    options = {v: k for k, v in SCHEDULE_DESC.items()}
    recipe_info["schedule"] = choose("Please select the relevant option:", options)


def toggle_start_time_estimation(context, recipe_info):
    context["start_time_estimation"] = not context["start_time_estimation"]


def edit_recipe(recipe_info):
    with alternate_screen_buffer():
        context = {"start_time_estimation": False}
        while True:
            clear_screen()
            print()
            print_recipe(recipe_info)
            valid = print_recipe_status(context, recipe_info)
            print()
            options = {
                "define WalT server site": (True, define_walt_server),
                "change WalT node counts": (True, change_walt_nodes),
                "change G5K reservation schedule": (True, change_schedule),
                "change G5K reservation walltime": (True, change_walltime),
                "toggle start time estimation": (True, toggle_start_time_estimation),
                "abort": (False, False),
            }
            if valid:
                options["validate and quit"] = (False, True)
            selected = choose("Select action:", options)
            if selected[0] is True:
                action = selected[1]
                print()
                action(context, recipe_info)
            else:
                return selected[1]
