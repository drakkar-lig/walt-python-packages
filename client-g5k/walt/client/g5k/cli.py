import sys

from walt.client.application import WalTApplication, WalTCategoryApplication
from walt.client.g5k.deploy import deploy
from walt.client.g5k.deploy.status import exit_if_walt_platform_deployed
from walt.client.g5k.printer import print_info
from walt.client.g5k.recipes import (
    edit_recipe,
    get_recipe_info,
    list_recipes,
    new_recipe,
    print_recipe,
    propose_save_recipe,
    remove_recipe,
    save_recipe,
)
from walt.client.g5k.release import release
from walt.client.g5k.types import G5K_RECIPE
from walt.client.g5k.wait import wait


# when working with grid'5000, the first thing we
# want to do is to deploy the WalT platform.
# so we set ORDERING to get this "g5k" category
# printed first.
class WalTG5K(WalTCategoryApplication):
    """commands to run WalT on Grid'5000"""

    ORDERING = 0


@WalTG5K.subcommand("deploy")
class WalTG5KDeploy(WalTApplication):
    """deploy WalT on Grid'5000 infrastructure"""

    ORDERING = 1

    def main(self, recipe_name: G5K_RECIPE = None):
        exit_if_walt_platform_deployed()
        if recipe_name is None:
            recipe_info = new_recipe()
            propose_save_recipe(recipe_info)
        else:
            recipe_info = get_recipe_info(recipe_name)
        deploy(recipe_info)


@WalTG5K.subcommand("wait")
class WalTG5KWait(WalTApplication):
    """wait for WalT platform to be deployed"""

    ORDERING = 2

    def main(self):
        wait()


@WalTG5K.subcommand("release")
class WalTG5KCancel(WalTApplication):
    """release current WalT platform from G5K"""

    ORDERING = 3

    def main(self):
        release()


@WalTG5K.subcommand("info")
class WalTG5KInfo(WalTApplication):
    """print info about your WalT platform"""

    ORDERING = 4

    def main(self):
        print_info()


@WalTG5K.subcommand("show-recipes")
class WalTG5KShowRecipes(WalTApplication):
    """list WalT deployment recipes"""

    ORDERING = 5

    def main(self):
        list_recipes()


@WalTG5K.subcommand("create-recipe")
class WalTG5KCreateRecipe(WalTApplication):
    """create a new WalT deployment recipe"""

    ORDERING = 6

    def main(self, recipe_name):
        # verify this name is not already taken
        get_recipe_info(recipe_name, expected=False)
        # create and save recipe
        recipe_info = new_recipe()
        save_recipe(recipe_name, recipe_info)


@WalTG5K.subcommand("edit-recipe")
class WalTG5KEditRecipe(WalTApplication):
    """edit a WalT deployment recipe"""

    ORDERING = 7

    def main(self, recipe_name: G5K_RECIPE):
        recipe_info = get_recipe_info(recipe_name)
        if edit_recipe(recipe_info):
            save_recipe(recipe_name, recipe_info)
        else:
            print("Aborted.")
            sys.exit(1)


@WalTG5K.subcommand("print-recipe")
class WalTG5KPrintRecipe(WalTApplication):
    """print a WalT deployment recipe"""

    ORDERING = 8

    def main(self, recipe_name: G5K_RECIPE):
        recipe_info = get_recipe_info(recipe_name)
        print_recipe(recipe_info)


@WalTG5K.subcommand("remove-recipe")
class WalTG5KRemoveRecipe(WalTApplication):
    """remove a WalT deployment recipe"""

    ORDERING = 9

    def main(self, recipe_name: G5K_RECIPE):
        remove_recipe(recipe_name)
