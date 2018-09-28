from plumbum import cli
from walt.client.link import ClientToServerLink
from walt.client.interactive import run_sql_prompt
from walt.client.auth import get_auth_conf
from walt.client.application import WalTCategoryApplication, WalTApplication

class WalTAdvanced(WalTCategoryApplication):
    """advanced sub-commands"""
    pass

@WalTAdvanced.subcommand("sql")
class WalTAdvancedSql(WalTApplication):
    """Start a remote SQL prompt on the WalT server database"""
    def main(self):
        run_sql_prompt()

@WalTAdvanced.subcommand("fix-image-owner")
class WalTAdvancedFixImageOwner(WalTApplication):
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

@WalTAdvanced.subcommand("update-hub-meta")
class WalTUpdateHubMeta(WalTApplication):
    """update hub metadata (docker images pushed without walt)"""
    _waltplatform_user = False # default
    def main(self):
        with ClientToServerLink() as server:
            auth_conf = get_auth_conf(server)
            server.update_hub_metadata(auth_conf, self._waltplatform_user)
    @cli.autoswitch(help='update waltplatform user (walt devs only)')
    def waltplatform_user(self):
        self._waltplatform_user = True

@WalTAdvanced.subcommand("rescan-hub-account")
class WalTRescanHubAccount(WalTUpdateHubMeta):
    """alias to 'update-hub-meta' subcommand"""
    pass
