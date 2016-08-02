#!/usr/bin/env python

from collections import OrderedDict

# special characters used to display the tree
WHOLE_V = u'\u2502'         # whole vertical bar
WHOLE_V_RIGHT_H = u'\u251c' # whole vertical + right horizontal bars
WHOLE_H = u'\u2500'         # whole horizontal bar
UPPER_V_RIGHT_H = u'\u2514' # upper vertical + right horizontal bars
SPACE = u' '

class Tree(object):
    """Class allowing to display an object hierarchy as a tree."""
    def __init__(self):
        self.nodes = OrderedDict()
        self.up_to_date = False
    def add_node(self, key, label, subtree_offset=0, parent_key = None):
        self.nodes[key] = dict(
            key=key,
            label=label,
            subtree_offset=subtree_offset,
            parent_key=parent_key)
        self.up_to_date = False
    def compute_children(self):
        for node in self.nodes.values():
            node['children'] = []
        for node in self.nodes.values():
            parent_key = node['parent_key']
            if parent_key != None:
                node_key = node['key']
                parent = self.nodes[parent_key]
                parent['children'].append(node_key)
    def printed(self, root):
        self.root_node = self.nodes[root]
        if self.up_to_date == False:
            self.compute_children()
            self.up_to_date = True
        return self.print_elem(**self.root_node)
    def print_elem(self, key, label, subtree_offset, parent_key, \
                        children, prefix = '', \
                        last_child = False, **kwargs):
        if self.root_node['key'] == key:  # root element
            output = "%s\n" % label
            prefix += (SPACE * subtree_offset)
        else:
            if last_child:
                sep_char_item = UPPER_V_RIGHT_H
                sep_char_child = SPACE
            else:
                sep_char_item = WHOLE_V_RIGHT_H
                sep_char_child = WHOLE_V
            output = "%s%s%s%s\n" % \
                    (prefix, sep_char_item, WHOLE_H, label)
            prefix += sep_char_child + (SPACE * (subtree_offset+1))
        num_children = len(children)
        for idx, child_key in enumerate(children):
                last_child = (idx == num_children-1)
                child = self.nodes[child_key]
                output += self.print_elem(
                                prefix = prefix,
                                last_child = last_child,
                                **child)
        return output

