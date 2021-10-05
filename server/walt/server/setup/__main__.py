import os
import sys

from walt.server.setup import WalTServerSetup

if os.geteuid() != 0:
    sys.exit("This script must be run as root. Exiting.")

WalTServerSetup.run()
