from walt.client.application import WalTApplication, WalTCategoryApplication
from walt.client.types import HELP_TOPIC


class WalTHelp(WalTCategoryApplication):
    """help sub-commands"""

    SUBCOMMAND_HELPMSG = False
    ORDERING = 7


@WalTHelp.subcommand("show")
class WalTHelpShow(WalTApplication):
    """displays help about a given topic"""

    USAGE = "walt help show [topic=help-intro]\n"

    def main(self, topic: HELP_TOPIC = "help-intro"):
        from walt.doc.md import display_doc

        display_doc(topic)


@WalTHelp.subcommand("list")
class WalTHelpList(WalTApplication):
    """displays the list of help topics"""

    def main(self):
        from walt.doc.md import display_topic_list

        display_topic_list()
