from collections import defaultdict


# Given a graph specified by a set of links (<node>, <node>)
# and a node which we know is part of a loop, this solver
# is able to find this loop.

# Try this for instance:
#
# links = (
#                 ("H", "G"),
#                 ("H", "E"),
#                 ("H", "F"),
#                 ("C", "D"),
#                 ("A", "E"),
#                 ("C", "E"),
#                 ("F", "I"),
#                 ("A", "M"),
#                 ("I", "J"),
#                 ("I", "K"),
#                 ("G", "L"),
#                 ("G", "M"),
#                 ("P", "Q"),
# )
# s = LoopsSolver()
# print(s.solve("A", links))
# -> prints ('A', 'E', 'H', 'G', 'M', 'A')
class LoopsSolver:
    def _set_subtree_connected(self, n):
        self._connected.add(n)
        for child_n, child_subtree in self._subtrees[n].copy().items():
            if child_n in self._connected:
                del self._subtrees[n][child_n]
            else:
                self._set_subtree_connected(child_n)
    def solve(self, base_node, links):
        self._subtrees = defaultdict(dict)
        self._connected = set((base_node,))
        for n1, n2 in links:
            if n1 in self._connected and n2 in self._connected:
                b, t1 = self._get_branch(base_node, n1)
                b, t2 = self._get_branch(base_node, n2)
                return t1 + tuple(reversed(t2))
            elif n1 in self._connected:
                self._subtrees[n1][n2] = self._subtrees[n2]
                self._set_subtree_connected(n2)
            elif n2 in self._connected:
                self._subtrees[n2][n1] = self._subtrees[n1]
                self._set_subtree_connected(n1)
            else:
                self._subtrees[n1][n2] = self._subtrees[n2]
                self._subtrees[n2][n1] = self._subtrees[n1]
    def _get_branch(self, orig, n):
        if orig == n:
            return True, (n,)
        for child_n in self._subtrees[orig]:
            res = self._get_branch(child_n, n)
            if res[0]:
                return True, (orig,) + res[1]
        return (False,)
