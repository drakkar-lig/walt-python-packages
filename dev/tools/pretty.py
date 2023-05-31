import sys

import black


def black_format(*paths):
    old_argv, old_exit = sys.argv, sys.exit
    sys.argv = ["black"] + list(str(path) for path in paths)
    sys.exit = lambda code=0: None
    black.main()
    sys.argv, sys.exit = old_argv, old_exit
