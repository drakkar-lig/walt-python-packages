from time import time

# The DHCP & NFS services are restarted (not reloaded) when configuration
# changes, because dhcpd does not support a simple SIGHUP based reloading,
# and using reload on NFSd instead of restart would prevent the NFS clients
# no longer allowed to be disconnected immediately, which would prevent
# unmounting of images.

# These services can be restarted quite often when a large set of new nodes
# are being registered. This can cause heavy processing or even break because
# of systemd service restart limit.
# Here, we ensure only one restart command is running at a time,
# and with a minimal interval of 5 seconds between restarts.
# When the restart command completes and 5 more seconds are spent, we check if
# the config was updated again in the meanwhile; if yes, we loop again.
MIN_DELAY_BETWEEN_SERVICE_RESTARTS = 5


class ServiceRestarter:
    def __init__(self, ev_loop, short_service_name, systemd_service_name,
                 allow_reload=False):
        self.ev_loop = ev_loop
        self.short_service_name = short_service_name
        self.systemd_service_name = systemd_service_name
        self.service_version = 0
        self.config_version = 0
        if allow_reload:
            self.systemd_op = "reload-or-restart"
        else:
            self.systemd_op = "restart"
        self.restarting = False
        self.callbacks = {}

    def inc_config_version(self):
        self.config_version += 1
        print(
            f"{self.short_service_name} conf updated (version {self.config_version})."
        )

    def uptodate(self):
        return self.config_version == self.service_version

    def restart(self, cb=None):
        if cb is not None:
            self.callbacks[self.config_version] = cb
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

            def callback():
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
                    cb = self.callbacks.get(v, None)
                    if cb is not None:
                        del self.callbacks[v]
                        cb()

            self.ev_loop.do(
                    f"systemctl {self.systemd_op} {self.systemd_service_name}",
                    callback)
