import json
import re
import sys

from plumbum.cli.terminal import ask, prompt
from walt.client.g5k.recipes.const import (
    DEFAULT_SCHEDULING,
    DEFAULT_WALLTIME,
    RECIPES_STORAGE_DIR,
)
from walt.client.g5k.recipes.editor import edit_recipe
from walt.common.formatting import columnate

ERROR_BAD_RECIPE_NAME = """\
Only lowercase letters, digits and dash(-) characters are allowed.
"""
ERROR_RECIPE_NAME_EXISTS = """\
A recipe with this name already exists.
"""
ERROR_RECIPE_NOT_FOUND = """\
Sorry, did not find a recipe with this name.
"""


def blank_recipe():
    return {
        "server": {
            "site": None,
        },
        "node_counts": {},
        "schedule": DEFAULT_SCHEDULING,
        "walltime": DEFAULT_WALLTIME,
    }


def new_recipe():
    recipe_info = blank_recipe()
    if not edit_recipe(recipe_info):
        print("Aborted.")
        sys.exit(1)
    return recipe_info


def recipe_name_validator(recipe_name):
    if not re.match(r"^[a-z0-9\-]+$", recipe_name):
        sys.stderr.write(ERROR_BAD_RECIPE_NAME)
        return False
    # check if another recipe already has this name
    recipe_info = get_recipe_info(recipe_name, expected=None)
    if recipe_info is not None:
        sys.stderr.write(ERROR_RECIPE_NAME_EXISTS)
        return False
    return True  # ok


def propose_save_recipe(recipe_info):
    should_save = ask("Do you wish to save this deployment recipe for later reuse?")
    if should_save:
        recipe_name = prompt("Recipe name", validator=recipe_name_validator)
        save_recipe(recipe_name, recipe_info)
        print("Saved. To re-deploy it, use: walt g5k deploy " + recipe_name)


def ensure_recipes_dir_exists():
    if not RECIPES_STORAGE_DIR.exists():
        RECIPES_STORAGE_DIR.mkdir(parents=True)


def get_recipe_file(recipe_name):
    return RECIPES_STORAGE_DIR / (recipe_name + ".json")


def get_recipe_info(recipe_name, expected=True):
    recipe_file = get_recipe_file(recipe_name)
    if recipe_file.exists():
        if expected is True or expected is None:
            return json.loads(recipe_file.read_text())
        elif expected is False:
            sys.stderr.write(ERROR_RECIPE_NAME_EXISTS)
            sys.exit(1)
    else:
        if expected is True:
            sys.stderr.write(ERROR_RECIPE_NOT_FOUND)
            sys.exit(1)
        elif expected is False or expected is None:
            return None


def save_recipe(recipe_name, recipe_info):
    ensure_recipes_dir_exists()
    recipe_file = get_recipe_file(recipe_name)
    recipe_file.write_text(json.dumps(recipe_info))


def list_recipes(names_only=False):
    ensure_recipes_dir_exists()
    recipe_names = [entry.name[:-5] for entry in RECIPES_STORAGE_DIR.iterdir()]
    if names_only:
        return "\n".join(recipe_names)
    if len(recipe_names) == 0:
        print("Found no recipes.")
    else:
        rows = [(name,) for name in recipe_names]
        print(columnate(rows, ["recipe name"]))


def remove_recipe(recipe_name):
    recipe_file = get_recipe_file(recipe_name)
    if not recipe_file.exists():
        sys.stderr.write(ERROR_RECIPE_NOT_FOUND)
        sys.exit(1)
    else:
        recipe_file.unlink()
