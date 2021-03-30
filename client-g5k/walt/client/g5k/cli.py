from walt.client.application import WalTCategoryApplication, WalTApplication

class WalTG5K(WalTCategoryApplication):
    """Commands to run WalT on Grid'5000"""
    pass

@WalTG5K.subcommand("deploy")
class WalTG5KDeploy(WalTApplication):
    """deploy WalT on Grid'5000 infrastructure"""
    def main(self):
        print('Done ;)')
