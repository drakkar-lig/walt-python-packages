from walt.client.application import WalTCategoryApplication, WalTApplication

class WalTHelp(WalTCategoryApplication):
    """help sub-commands"""
    SUBCOMMAND_HELPMSG = False
    ORDERING = 7

@WalTHelp.subcommand("show")
class WalTHelpShow(WalTApplication):
    """displays help about a given topic"""
    USAGE = 'walt help show [topic=help-intro]\n'
    def main(self, topic = 'help-intro'):
        from walt.client.doc.md import display_doc
        display_doc(topic)

@WalTHelp.subcommand("list")
class WalTHelpList(WalTApplication):
    """displays the list of help topics"""
    def main(self):
        from walt.client.doc.md import display_topic_list
        display_topic_list()

WALT_CLIENT_CATEGORY = "help", WalTHelp
