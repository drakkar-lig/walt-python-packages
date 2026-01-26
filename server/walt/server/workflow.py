import functools
import numpy as np
import sys


class Workflow:
    _next_id = 0
    _instances = {}
    def __init__(self, steps, **env):
        self._id = Workflow._next_id
        Workflow._next_id += 1
        self._steps = list(steps)
        self._env = env
        self._end_callbacks = []
        Workflow._instances[self._id] = self
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
        elif not self.done:  # because wf.interrupt() may be called at any time
            #print(f"<Workflow{self._id}> end")
            end_callbacks = self._end_callbacks
            self._end_callbacks = None
            for cb in end_callbacks:
                cb()
            del Workflow._instances[self._id]

    def interrupt(self):
        self._steps = []
        self.next()  # end properly and call optional callbacks

    def update_env(self, **env):
        self._env.update(**env)

    def run(self):
        self.next()

    @classmethod
    def can_end_evloop(cls):
        return len(Workflow._instances) == 0

    @classmethod
    def cleanup_remaining_workflows(cls):
        for wf in list(Workflow._instances.values()):
            if not wf.done:
                wf.print_missed()
                print(f"{wf} was never properly ended.", file=sys.stderr)
                wf.interrupt()
        Workflow._instances = {}

    def insert_steps(self, steps):
        self._steps = list(steps) + self._steps

    def append_steps(self, steps):
        self._steps = self._steps + list(steps)

    @staticmethod
    def _wf_run_parallel_steps(wf, _parallel_steps, **env):
        num_parallel_steps = len(_parallel_steps)
        wf.update_env(_remaining_parallel_steps = num_parallel_steps)
        wf.insert_steps([wf._wf_after_one_parallel_step] * num_parallel_steps)
        for step in _parallel_steps:
            step(wf, **env)

    @staticmethod
    def _wf_after_one_parallel_step(wf, _remaining_parallel_steps, **env):
        _remaining_parallel_steps -= 1
        if _remaining_parallel_steps == 0:
            wf.next()  # all parallel steps are done
        else:
            wf.update_env(_remaining_parallel_steps = _remaining_parallel_steps)

    def insert_parallel_steps(self, steps):
        self.update_env(_parallel_steps = steps)
        self.insert_steps([self._wf_run_parallel_steps])

    @staticmethod
    def _mapped_parallel_step(f, f_args, wf, **env):
        # notes:
        # * arguments (f, f_args) are given in advance
        #   by the partial() function (see below).
        # * arguments (wf, **env) are added when called
        #   by self.next()
        f(wf, *f_args, **env)

    def map_as_parallel_steps(self, f, *f_args):
        partial = functools.partial(functools.partial, self._mapped_parallel_step, f)
        steps = list(map(partial, zip(*f_args)))
        self.insert_parallel_steps(steps)

    def continue_after_other_workflow(self, other_wf):
        #print("continue_after_other_workflow")
        other_wf._end_callbacks.append(self.next)

    def print_missed(self):
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

    def __del__(self):
        if not self.done:
            self.print_missed()
            print(f"{self} was not ended when garbage collected.", file=sys.stderr)
            del Workflow._instances[self._id]
