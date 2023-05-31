from collections import defaultdict
from functools import cache

# Sample use:
#
# >>> from autoglob import autoglob
# >>> words = [ 'rpi-b', 'rpi-2-b', 'rpi-3-b', 'qemu-arm', 'pc-x86-64', 'pc-x86-32' ]
# >>> print(autoglob(words))
# rpi-[b,2-b,3-b],qemu-arm,pc-x86-[64,32]
# >>>
#
# The algorithm is not perfect but should be enough when doing prefix match.


class State:
    def __init__(self, graph, name):
        self.graph = graph
        self.name = name
        self.routes = {}
        self.ref_count = 0

    def next(self, transition):
        return self.routes[transition]

    def is_used(self):
        return self.ref_count > 0 or self.name == "__START__"

    def simplify(self):
        if self.name == "__START__":
            return False
        if len(self.routes) == 0:
            return False
        target_states = set(self.routes.values())
        if len(target_states) > 1:
            return False
        target_state = target_states.pop()
        if target_state.name == "__END__":
            return False
        for transition in list(self.routes.keys()):
            next_transition = self.graph.next_transitions[transition]
            self.routes[transition] = target_state.routes[next_transition]
            del target_state.routes[next_transition]
            target_state.ref_count -= 1
            next_next_transition = self.graph.next_transitions.get(
                next_transition, None
            )
            if next_next_transition is None:
                del self.graph.next_transitions[transition]
            else:
                self.graph.next_transitions[transition] = next_next_transition
                del self.graph.next_transitions[next_transition]
        self.name += target_state.name
        return True

    def autoglob(self, current_transitions=None):
        if self.name == "__END__":
            return ""
        if current_transitions is None:
            current_transitions = tuple(self.routes.keys())
        selected_targets = defaultdict(set)
        for transition, target_state in self.routes.items():
            if transition not in current_transitions:
                continue
            selected_targets[target_state].add(transition)
        target_globs = []
        for target_state, transitions in selected_targets.items():
            target_transitions = tuple(
                self.graph.next_transitions.get(transition)
                for transition in transitions
            )
            target_globs.append(target_state.autoglob(target_transitions))
        if self.name == "__START__":
            return ",".join(target_globs)
        # if target_globs are <value> and <empty> this means that <value> is optional
        # in this case just return [<value>] and not [|<value>]
        if len(target_globs) == 2 and "" in target_globs:
            optional_value = True
            target_globs_option1 = [tglob for tglob in target_globs if tglob != ""]
        else:
            optional_value = False
            target_globs_option1 = target_globs
        option1 = self.name + "[" + "|".join(target_globs_option1) + "]"
        option2 = ",".join((self.name + tglob) for tglob in target_globs)
        if len(option1) < len(option2):
            return option1
        elif len(option1) > len(option2):
            return option2
        elif optional_value:  # same length, but optional value notation may be
            # more readable
            return option1
        else:  # same length, so keep it simple and repeat prefix
            return option2

    def __str__(self):
        lines = [self.name]
        for transition, state in self.routes.items():
            lines.append(" %d -> %s" % (transition, state.name))
        lines += [""]
        return "\n".join(lines)


class HyperGraph:
    def __init__(self):
        self.states = None
        self.next_transitions = None

    def register_state(self, state_name):
        state = State(self, state_name)
        self.states[state_name] = state
        return state

    def construct(self, words):
        self.states = {}
        self.next_transitions = {}
        prev_state = None
        self.start_state = self.register_state("__START__")
        transition = 0
        for word in words:
            spelled = ["__START__"] + list(word) + ["__END__"]
            for state_name in spelled:
                if state_name not in self.states:
                    self.register_state(state_name)
                state = self.states[state_name]
                if state_name != "__START__":
                    assert prev_state is not None
                    prev_state.routes[transition] = state
                    self.next_transitions[transition - 1] = transition
                    state.ref_count += 1
                prev_state = state
                transition += 1

    def simplify(self):
        while True:
            changed = False
            for state_name, state in list(self.states.items()):
                if not state.is_used():
                    del self.states[state_name]
                    changed = True
                if state.simplify():
                    changed = True
            if not changed:
                break

    def autoglob(self):
        return self.start_state.autoglob()


@cache
def autoglob_with_cache(words):
    graph = HyperGraph()
    graph.construct(words)
    graph.simplify()
    return graph.autoglob()


def autoglob(words):
    if len(words) == 1:
        return words[0]
    return autoglob_with_cache(tuple(words))
