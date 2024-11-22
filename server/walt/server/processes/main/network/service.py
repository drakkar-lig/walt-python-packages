from collections import defaultdict
from time import time

# The DHCP service is restarted (not reloaded) when configuration changes,
# because dhcpd does not support a simple SIGHUP based reloading.

# DHCP and NAMED services can be restarted quite often when a large set of
# new nodes are being registered. This can cause heavy processing or even
# break because of systemd service restart limit.
# Here, we ensure only one restart command is running at a time,
# and with a minimal interval of 5 seconds between restarts.
# When the restart command completes and 5 more seconds are spent, we check if
# the config was updated again in the meantime; if yes, we loop again.
MIN_DELAY_BETWEEN_SERVICE_RESTARTS = 5


# note: using busctl is faster than calling systemctl [reload|restart] <unit>
# but it does not wait for the service to be restarted, so it may not
# be suitable for all cases (e.g., when umounting images, we have to wait
# until nfs releases the export otherwise "umount" of the underlying overlay
# filesystem will fail).
def async_systemd_service_restart_cmd(systemd_service_name, allow_reload=False):
    systemd_op = "ReloadOrRestartUnit" if allow_reload else "RestartUnit"
    return ("busctl call org.freedesktop.systemd1 /org/freedesktop/systemd1 "
            f"org.freedesktop.systemd1.Manager {systemd_op} "
            f"ss {systemd_service_name} replace")


class ServiceRestarter:
    def __init__(self, ev_loop, short_service_name, restart_cmd):
        self.ev_loop = ev_loop
        self.short_service_name = short_service_name
        self.service_version = 0
        self.config_version = 0
        self.restart_cmd = restart_cmd
        self.restarting = False
        self.callbacks = defaultdict(list)

    def inc_config_version(self):
        self.config_version += 1
        print(
            f"{self.short_service_name} conf updated (version {self.config_version})."
        )

    def uptodate(self):
        return self.config_version == self.service_version

    def restart(self, cb=None):
        if cb is not None:
            self.callbacks[self.config_version].append(cb)
        if not self.restarting:
            self.restarting = True
            self.restart_service_loop()

    def restart_service_loop(self):
        if self.config_version == self.service_version:
            # ok done
            self.restarting = False
            return
        else:
            next_service_version = self.config_version
            print(
                f"{self.short_service_name} restarting with version"
                f" {next_service_version}."
            )

            def callback(retcode):
                # update service version
                prev_service_version = self.service_version
                self.service_version = next_service_version
                # compute time of next call
                target_ts = time() + MIN_DELAY_BETWEEN_SERVICE_RESTARTS
                # plan event to be recalled at this time
                self.ev_loop.plan_event(
                    ts=target_ts, callback=self.restart_service_loop
                )
                # call user provided callbacks
                for v in range(prev_service_version + 1, next_service_version + 1):
                    for cb in self.callbacks.pop(v, ()):
                        cb()

            self.ev_loop.do(self.restart_cmd, callback)
