import sys

class Workflow:
    _next_id = 0
    def __init__(self, steps, **env):
        self._id = Workflow._next_id
        Workflow._next_id += 1
        self._steps = list(steps)
        self._env = env
        self._end_callbacks = []
        #print(f"new {self}")

    def __repr__(self):
        return f"<Workflow{self._id}>"

    def get_env(self):
        return self._env

    @property
    def done(self):
        return self._end_callbacks is None

    def next(self, *args, **kwargs):
        if len(self._steps) > 0:
            step, self._steps = self._steps[0], self._steps[1:]
            env = self._env.copy()
            env.update(**kwargs)
            #print(f"<Workflow{self._id}>.next()", step)
            step(self, *args, **env)
        else:
            #print(f"<Workflow{self._id}> terminated")
            end_callbacks = self._end_callbacks
            self._end_callbacks = None
            for cb in end_callbacks:
                cb()

    def interrupt(self):
        self._steps = []
        self.next()  # end properly and call optional callbacks

    def update_env(self, **env):
        self._env.update(**env)

    def run(self):
        self.next()

    def join(self, ev_loop):
        if not self.done:
            ev_loop.loop(lambda: not self.done)

    def insert_steps(self, steps):
        self._steps = list(steps) + self._steps

    def append_steps(self, steps):
        self._steps = self._steps + list(steps)

    def continue_after_other_workflow(self, other_wf):
        #print("continue_after_other_workflow")
        other_wf._end_callbacks.append(self.next)

    def __del__(self):
        if not self.done:
            num_steps = len(self._steps)
            if num_steps > 0:
                print(f"{self} missed {num_steps} steps:", file=sys.stderr)
                for step in self._steps:
                    print(step, file=sys.stderr)
            num_callbacks = len(self._end_callbacks)
            if num_callbacks > 0:
                print(f"{self} missed {num_callbacks} callbacks:", file=sys.stderr)
                for cb in self._end_callbacks:
                    print(cb, file=sys.stderr)
            print(f"{self} was interrupted.", file=sys.stderr)
