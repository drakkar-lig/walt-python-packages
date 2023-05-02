
class Workflow:
    def __init__(self, steps, **env):
        self._steps = list(steps)
        self._env = env
    def get_env(self):
        return self._env
    def next(self, *args, **kwargs):
        step, self._steps = self._steps[0], self._steps[1:]
        env = self._env.copy()
        env.update(**kwargs)
        step(self, *args, **env)
    def update_env(self, **env):
        self._env.update(**env)
    def run(self):
        self.next()
    def insert_steps(self, steps):
        self._steps = list(steps) + self._steps
