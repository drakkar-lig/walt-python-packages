#!/usr/bin/env python
from itertools import count
from collections import defaultdict

class Grouper:
    def __init__(self):
        self.group_ids = count()
        self.items_per_group_id = defaultdict(set)
        self.group_id_per_item = {}
    def add_isolated_item(self, item):
        group_id = next(self.group_ids)
        self.items_per_group_id[group_id].add(item)
        self.group_id_per_item[item] = group_id
        return group_id
    def get_group_id(self, item):
        group_id = self.group_id_per_item.get(item, None)
        if group_id is None:
            # item was not known yet, register it
            group_id = self.add_isolated_item(item)
        return group_id
    def group_items(self, item1, item2):
        item1_group_id = self.get_group_id(item1)
        item2_group_id = self.get_group_id(item2)
        item2_friends = self.items_per_group_id.pop(item2_group_id)
        for item in item2_friends:
            self.group_id_per_item[item] = item1_group_id
        self.items_per_group_id[item1_group_id] |= item2_friends
    def num_groups(self):
        return len(self.items_per_group_id)
    def is_same_group(self, item1, item2):
        return self.get_group_id(item1) == self.get_group_id(item2)
    def __contains__(self, item):
        return item in self.group_id_per_item
    def debug(self):
        for group_id, items in self.items_per_group_id.items():
            print group_id, items
