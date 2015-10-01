from plumbum import cli
from walt.client.link import ClientToServerLink
from walt.client.interactive import run_sql_prompt

class WalTAdvanced(cli.Application):
    """advanced sub-commands"""
    pass

@WalTAdvanced.subcommand("sql")
class WalTAdvancedSql(cli.Application):
    """Start a remote SQL prompt on the WalT server database"""
    def main(self):
        run_sql_prompt()

@WalTAdvanced.subcommand("fix-image-owner")
class WalTAdvancedFixImageOwner(cli.Application):
    """fix the owner of images"""
    _force = False # default
    def main(self, other_user):
        if not self._force:
            print """\
This will make you own all images of user '%s'. It is intended
for maintenance only (i.e. if user '%s' is no longer working with
walt).
If this is really what you want, run:
walt advanced fix-image-owner --yes-i-know-do-it-please %s
""" % ((other_user,) * 3)
        else:
            with ClientToServerLink() as server:
                server.fix_image_owner(other_user)
    @cli.autoswitch(help='yes, I know, do it!')
    def yes_i_know_do_it_please(self):
        self._force = True

