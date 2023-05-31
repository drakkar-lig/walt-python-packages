from walt.client.g5k.recipes.manager import list_recipes


def shell_completion_hook(argv):
    arg_type = argv[0]
    if arg_type == "G5K_RECIPE":
        return " ".join(list_recipes(names_only=True).split())
    else:
        # this plugin does not know how to complete other types
        return None
