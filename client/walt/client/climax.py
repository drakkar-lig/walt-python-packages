
class Internals:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

class Application:
    classmethod
    def get(cls):
        if not hasattr(cls, '_instance'):
            cls._instance = cls()
        return cls._instance
    def __init__(self):
        self.__internals = Internals(
            subcommands = []
        )
    def subcommand(cls, subcommand):
        self.get().__internals.subcommands.append(subcommand)
