from walt.common.setup import WaltGenericSetup

ENABLED_SYSTEMD_SERVICES = {
    "walt-server.service": {},
    "walt-server-netconfig.service": {},
    "walt-server-dhcpd.service": {
        'WantedBy': "walt-server-netconfig.service"
    },
    "walt-server-tftpd.service": {
        'WantedBy': "walt-server-netconfig.service"
    },
    "walt-server-snmpd.service": {
        'WantedBy': "walt-server-netconfig.service"
    },
    "walt-server-lldpd.service": {
        'WantedBy': "walt-server-netconfig.service"
    },
    "walt-server-ptpd.service": {
        'WantedBy': "walt-server-netconfig.service"
    },
    "walt-server-httpd.service": {
        'WantedBy': "walt-server.service"
    }
}

# WALT has its own version of the following services.
# Since in their default configuration they would conflict with these
# walt services, we have to disable them.
DISABLED_SYSTEMD_SERVICES = [
    'tftpd-hpa', 'isc-dhcp-server', 'snmpd', 'lldpd', 'ptpd'
]

class WalTServerSetup(WaltGenericSetup):
    package = __name__

    @property
    def display_name(self):
        return "WalT server"

    def main(self):
        """install WalT server software"""
        self.setup_systemd_services(ENABLED_SYSTEMD_SERVICES)
        self.disable_systemd_services(DISABLED_SYSTEMD_SERVICES)

def run():
    WalTServerSetup.run()
