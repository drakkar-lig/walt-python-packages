from pathlib import Path

from pkg_resources import resource_string

from walt.common.tools import failsafe_symlink

SYSTEMD_SERVICES_DEF = {
            "walt-server.service": None,
            "walt-server-netconfig.service": None,
            "walt-server-dhcpd.service": "walt-server-netconfig.service",
            "walt-server-httpd.service": "walt-server.service"
}
SYSTEMD_DEFAULT_DIR = Path("/etc/systemd/system")


def setup_systemd(systemd_dir: Path = SYSTEMD_DEFAULT_DIR):
    for service, wanted_by in SYSTEMD_SERVICES_DEF.items():
        service_file_content = resource_string(__name__, service)
        service_file_path = systemd_dir / service
        if service_file_path.exists():
            print('Overwriting ' + str(service_file_path))
        service_file_path.write_bytes(service_file_content)
        if wanted_by is not None:
            # the following is the same as running 'systemctl enable <service>'
            # on a system that is really running
            systemd_install_dir = systemd_dir / (wanted_by + '.wants')
            failsafe_symlink(str(service_file_path),
                             str(systemd_install_dir / service))
