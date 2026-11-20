#!/usr/bin/env python
import functools
import inspect

from plumbum import cli
from plumbum.lib import getdoc


def _wrap_main(main):
    # By convention, the main() method of walt commands returns False on
    # failure (and possibly True on success). Plumbum uses the return value
    # of main() as the exit code, so we convert False to 1 and True to 0.
    # Note: we cannot do this after plumbum returns, because plumbum >= 2
    # replaces a False exit code by 0 (it returns "retcode or 0").
    @functools.wraps(main)
    def wrapped_main(self, *args, **kwargs):
        res = main(self, *args, **kwargs)
        if res is False:
            return 1
        if res is True:
            return 0
        return res

    # plumbum reads the positional arguments of main() (and their
    # validators) with inspect.getfullargspec(), which ignores the
    # __wrapped__ attribute set by functools.wraps(), so we have to
    # specify the signature explicitly.
    wrapped_main.__signature__ = inspect.signature(main)
    return wrapped_main


class WalTApplication(cli.Application):
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        main = cls.__dict__.get("main")
        if main is not None:
            cls.main = _wrap_main(main)


WalTApplication.unbind_switches("-v", "--version", "--help-all",
                                "--completions")


class WalTToolboxApplication(WalTApplication):
    @cli.switch(["-h", "--help"], group="Meta-switches")
    def help(self):
        """Prints this help message and quits"""
        print((self.get_help_prefix().rstrip()))
        # order sub-commands or categories by their ORDERING field
        # if they provide one, by their name otherwise
        ordering = []
        for name, subcls in self._subcommands.items():
            subapp = subcls.get()
            priority = getattr(subapp, "ORDERING", 0)
            ordering.append((priority, name, subapp))
        subitems = []
        for priority, name, subapp in sorted(ordering):
            doc = subapp.DESCRIPTION if subapp.DESCRIPTION else getdoc(subapp)
            subitems.append((name, doc))
        max_name_len = max(len(name) for name, doc in subitems)
        format_str = "    %-" + str(max_name_len) + "s  %s"
        for name, doc in subitems:
            print((format_str % (name, doc)))
        print()


WALT_CATEGORY_COMMAND_HELP_PREFIX = """
WalT platform control tool
-> %(category_desc)s

Usage:
    walt %(category_name)s SUBCOMMAND [args...]

Help about a given subcommand:
    walt %(category_name)s SUBCOMMAND --help

Help about WalT in general:
    walt help show

Sub-commands:
"""


class WalTCategoryApplication(WalTToolboxApplication):
    def get_help_prefix(self):
        return WALT_CATEGORY_COMMAND_HELP_PREFIX % dict(
            category_name=self.get_category_name(),
            category_desc=self.get_category_short_desc(),
        )

    def get_category_name(self):
        return self.PROGNAME.split()[-1]

    def get_category_short_desc(self):
        return self.DESCRIPTION if self.DESCRIPTION else getdoc(self)
