def get_total_node_count(recipe_info):
    if len(recipe_info["node_counts"]) == 0:
        return 0
    return sum(recipe_info["node_counts"].values())
