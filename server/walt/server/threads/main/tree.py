#!/usr/bin/env python

from collections import OrderedDict
from walt.server.tools import try_encode

# special characters used to display the tree (if possible)
class UNICODE_CHARSET:
    WHOLE_V = u'\u2502'         # whole vertical bar
    WHOLE_V_RIGHT_H = u'\u251c' # whole vertical + right horizontal bars
    WHOLE_H = u'\u2500'         # whole horizontal bar
    UPPER_V_RIGHT_H = u'\u2514' # upper vertical + right horizontal bars
    SPACE = u' '

SPECIAL_CHARS = ''.join(
        v for k, v in UNICODE_CHARSET.__dict__.items() \
                if isinstance(v, unicode))

# simpler characters (fallback)
class ASCII_CHARSET:
    WHOLE_V = '|'
    WHOLE_V_RIGHT_H = '|'
    WHOLE_H = '-'
    UPPER_V_RIGHT_H = '|'
    SPACE = ' '

class Tree(object):
    """Class allowing to display an object graph as a tree."""
    def __init__(self, stdout_encoding):
        self.nodes = OrderedDict()
        self.up_to_date = False
        if try_encode(SPECIAL_CHARS, stdout_encoding):
            self.charset = UNICODE_CHARSET
        else:
            self.charset = ASCII_CHARSET
    def add_node(self, key, label):
        self.nodes[key] = dict(
            key=key,
            label=label,
            children=[])
        self.up_to_date = False
    def add_child(self, node_key, child_pos, child_key):
        self.nodes[node_key]['children'].append((child_pos, child_key))
    def sort_children(self):
        # sort children by child_pos
        for node in self.nodes.values():
            node['children'] = sorted(node['children'])
    def printed(self, root):
        self.root_node = self.nodes[root]
        if self.up_to_date == False:
            self.sort_children()
            self.up_to_date = True
        return self.print_elem(**self.root_node)
    def print_elem(self, key, label, children,
                        child_pos = None, prefix = '',
                        last_child = False, seen = None, **kwargs):
        if seen == None:
            seen = set()
        if self.root_node['key'] == key and key not in seen:  # root element
            output = "%s\n" % label
            # align to 2nd letter of the name
            subtree_offset = 1
            prefix += (self.charset.SPACE * subtree_offset)
        else:
            if key in seen:
                label = '[back to %s]' % label
            if child_pos == None:
                subtree_offset = 1
            else:
                label = "%d: %s" % (child_pos, label)
                # align to 2nd letter of the name
                subtree_offset = len("%d" % child_pos) + 2
            if last_child:
                sep_char_item = self.charset.UPPER_V_RIGHT_H
                sep_char_child = self.charset.SPACE
            else:
                sep_char_item = self.charset.WHOLE_V_RIGHT_H
                sep_char_child = self.charset.WHOLE_V
            output = "%s%s%s%s\n" % \
                    (prefix, sep_char_item, self.charset.WHOLE_H, label)
            prefix += sep_char_child + (self.charset.SPACE * (subtree_offset+1))
        if key not in seen:
            seen.add(key)
            num_children = len(children)
            for idx, child in enumerate(children):
                    child_pos, child_key = child
                    last_child = (idx == num_children-1)
                    child = self.nodes[child_key]
                    output += self.print_elem(
                                    child_pos = child_pos,
                                    prefix = prefix,
                                    last_child = last_child,
                                    seen = seen,
                                    **child)
        return output

