from plumbum import cli
from walt.client.application import WalTApplication, WalTCategoryApplication
from walt.client.interactive import run_sql_prompt
from walt.client.link import ClientToServerLink


class WalTAdvanced(WalTCategoryApplication):
    """advanced sub-commands"""

    ORDERING = 6


@WalTAdvanced.subcommand("sql")
class WalTAdvancedSql(WalTApplication):
    """start a remote SQL prompt on the WalT server database"""

    def main(self):
        run_sql_prompt()


@WalTAdvanced.subcommand("fix-image-owner")
class WalTAdvancedFixImageOwner(WalTApplication):
    """fix the owner of images"""

    _force = False  # default

    def main(self, other_user):
        if not self._force:
            print("""\
This will make you own all images of user '%s'. It is intended
for maintenance only (i.e. if user '%s' is no longer working with
walt).
If this is really what you want, run:
walt advanced fix-image-owner --yes-i-know-do-it-please %s
""" % ((other_user,) * 3))
        else:
            with ClientToServerLink() as server:
                server.fix_image_owner(other_user)

    @cli.autoswitch(help="yes, I know, do it!")
    def yes_i_know_do_it_please(self):
        self._force = True


@WalTAdvanced.subcommand("update-hub-meta")
class WalTUpdateHubMeta(WalTApplication):
    """update hub metadata (docker images pushed without walt)"""

    _waltplatform_user = False  # default

    def main(self):
        with ClientToServerLink() as server:
            registries = server.get_registries()
            if "hub" not in tuple(reg_info[0] for reg_info in registries):
                print(
                    "Sorry, cannot run this command because the docker hub registry was"
                    " disabled on this platform."
                )
                return False
            return server.update_hub_metadata(self._waltplatform_user)

    @cli.autoswitch(help="update waltplatform user (walt devs only)")
    def waltplatform_user(self):
        self._waltplatform_user = True


@WalTAdvanced.subcommand("rescan-hub-account")
class WalTRescanHubAccount(WalTUpdateHubMeta):
    """alias to 'update-hub-meta' subcommand"""

    pass


@WalTAdvanced.subcommand("dump-bash-autocomplete")
class WalTDumpBashAutocomplete(WalTApplication):
    """dump bash auto-completion code"""

    def main(self):
        import walt.client.autocomplete.dump as dumper

        dumper.dump_bash_autocomplete(self)


@WalTAdvanced.subcommand("dump-zsh-autocomplete")
class WalTDumpZshAutocomplete(WalTApplication):
    """dump zsh auto-completion code"""

    def main(self):
        import walt.client.autocomplete.dump as dumper

        dumper.dump_zsh_autocomplete(self)


@WalTAdvanced.subcommand("update-default-images")
class WalTUpdateDefaultImages(WalTApplication):
    """update default images (images of free nodes)"""

    def main(self):
        with ClientToServerLink() as server:
            return server.update_default_images()
