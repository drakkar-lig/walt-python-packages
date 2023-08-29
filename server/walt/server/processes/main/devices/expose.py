import re
import socket
from walt.common.tcp import server_socket
from walt.common.tools import set_close_on_exec


class SocketForwarder:

    def __init__(self, sock_src, sock_dst):
        self.sock_src = sock_src
        self.sock_dst = sock_dst

    def fileno(self):
        return self.sock_src.fileno()

    def handle_event(self, ts):
        try:
            buf = self.sock_src.recv(4096)
            if len(buf) == 0:
                # empty read, close
                return False
            self.sock_dst.sendall(buf)
        except Exception:
            return False  # issue, close

    def close(self):
        self.sock_src.close()
        self.sock_dst.close()


class ExposeRedirect:

    def __init__(self, manager, server_port,
                 device_ip, device_port):
        self._ev_loop = manager.server.ev_loop
        self.server_port = server_port
        self.device_ip = device_ip
        self.device_port = device_port

    def start(self):
        self._s = server_socket(self.server_port)
        self._ev_loop.register_listener(self)

    def fileno(self):
        return self._s.fileno()

    def handle_event(self, ts):
        try:
            s_to_client, addr = self._s.accept()
        except Exception:
            return False
        s_to_device = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            set_close_on_exec(s_to_device, True)
            s_to_device.connect((self.device_ip, self.device_port))
        except Exception:
            s_to_device.close()
            s_to_client.close()
            # even if there was an issue while contacting the device,
            # the server itself should continue running
            return True
        # forward in both ways
        for forwarder in (SocketForwarder(s_to_client, s_to_device),
                          SocketForwarder(s_to_device, s_to_client)):
            self._ev_loop.register_listener(forwarder)

    def close(self):
        self._s.close()


class ExposeManager:

    def __init__(self, server):
        self.server = server
        self.redirects = {}  # { <server_port>: <ExposeRedirect object> }

    def parse_expose_setting_value(self, setting_value):
        if setting_value != "none" and \
           re.match(r"^\d+:\d+(,\d+:\d+)*$", setting_value) is None:
            return (False,)
        _redirects = []
        if setting_value != "none":
            for redirect in setting_value.split(","):
                device_port_s, server_port_s = redirect.split(':')
                _redirects.append((int(device_port_s), int(server_port_s)))
        return (True, _redirects)

    def check_expose_setting_value(self, requester, device_ip, setting_value):
        parsed = self.parse_expose_setting_value(setting_value)
        if not parsed[0]:
            requester.stderr.write(
                f"Failed: '{setting_value}' is not a valid value for option 'expose'.\n"
                "        Use for example '80:8088' "
                "(device port 80 <-> server port 8088).\n"
                "        Several redirects are possible, e.g., '80:8088,443:8443'.\n"
            )
            return False
        redirects = parsed[1]
        if len(redirects) == 0:
            return True  # OK
        device_ports, server_ports = tuple(zip(*redirects))
        if len(set(device_ports)) < len(redirects):
            requester.stderr.write(
                  "Failed: cannot use several times the same device port number.\n"
            )
            return False
        if len(set(server_ports)) < len(redirects):
            requester.stderr.write(
                  "Failed: cannot use several times the same server port number.\n"
            )
            return False
        for device_port, server_port in redirects:
            redir = self.redirects.get(server_port, None)
            if redir is None:
                # first time this server port is used, check if we can bind it
                check, err = self.check_bind_port(server_port)
                if not check:
                    requester.stderr.write(
                            f"Failed: cannot use server port '{server_port}': {err}.\n"
                    )
                    return False
            else:
                # this port is already in use for a redirect, check if this
                # is for the same device we are currently configuring.
                if device_ip != redir.device_ip:
                    requester.stderr.write(
                      f"Failed: server port '{server_port}' is already used "
                      "for another redirect.\n"
                    )
                    return False
        return True

    def check_bind_port(self, server_port):
        try:
            s = server_socket(server_port)
        except OSError as e:
            return (False, e.strerror)
        except Exception as e:
            return (False, str(e))
        s.close()
        return (True, None)

    def add_redirect(self, requester, server_port, device_ip, device_port):
        check, err = self.check_bind_port(server_port)
        if check:
            redir = ExposeRedirect(self, server_port, device_ip, device_port)
            redir.start()
            self.redirects[server_port] = redir
        else:
            logline = (f"Failed to expose {device_ip}:{device_port} "
                       "on server:{server_port}: {err} (bypassing)\n")
            if requester is None:
                self.server.logs.platform_log("expose", logline)
            else:
                requester.stderr.write(logline)

    def apply(self, requester, device_ip, setting_value):
        parsed = self.parse_expose_setting_value(setting_value)
        assert parsed[0] is True
        new_redirects = set(parsed[1])
        old_redirects = set(
                (redir.device_port, redir.server_port)
                for redir in self.redirects.values()
                if redir.device_ip == device_ip)
        # stop old redirects
        for device_port, server_port in old_redirects - new_redirects:
            redir = self.redirects.pop(server_port)
            redir.close()
        # create new redirects
        for device_port, server_port in new_redirects - old_redirects:
            self.add_redirect(requester, server_port, device_ip, device_port)

    def restore(self):
        for row in self.server.db.execute("""\
                SELECT ip, conf->'expose' as setting_value FROM devices
                WHERE conf->'expose' IS NOT NULL; """):
            parsed = self.parse_expose_setting_value(row.setting_value)
            assert parsed[0] is True
            redirects = parsed[1]
            for device_port, server_port in redirects:
                self.add_redirect(None, server_port, row.ip, device_port)
