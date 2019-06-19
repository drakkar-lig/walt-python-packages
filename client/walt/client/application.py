#!/usr/bin/env python
import walt.client.climax as cli

class WalTApplication(cli.Application):
    pass

class WalTToolboxApplication(WalTApplication):
    def help(self):
        """Prints this help message and quits"""
        print((self.get_help_prefix().rstrip()))
        subitems = []
        for name, subcls in sorted(self._subcommands.items()):
            subapp = subcls.get()
            doc = subapp.DESCRIPTION if subapp.DESCRIPTION else cli.getdoc(subapp)
            subitems.append((name, doc))
        max_name_len = max(len(name) for name, doc in subitems)
        format_str = '    %-' + str(max_name_len) + 's  %s'
        for name, doc in subitems:
            print((format_str % (name, doc)))

WALT_CATEGORY_COMMAND_HELP_PREFIX = '''
WalT platform control tool
-> %(category_desc)s

Usage:
    walt %(category_name)s SUBCOMMAND [args...]

Help about a given subcommand:
    walt %(category_name)s SUBCOMMAND --help

Help about WalT in general:
    walt help show

Sub-commands:
'''

class WalTCategoryApplication(WalTToolboxApplication):
    def get_help_prefix(self):
        return WALT_CATEGORY_COMMAND_HELP_PREFIX % dict(
            category_name = self.get_category_name(),
            category_desc = self.get_category_short_desc()
        )
    def get_category_name(self):
        return self.PROGNAME.split()[-1]
    def get_category_short_desc(self):
        return self.DESCRIPTION if self.DESCRIPTION else cli.getdoc(self)

