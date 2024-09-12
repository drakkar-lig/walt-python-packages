import re
import socket
from walt.common.tcp import server_socket
from walt.server.tools import NonBlockingSocket

SOCKET_TO_DEVICE_TIMEOUT = 2


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


# nodes are sometimes hard-rebooted, so TCP connections may not be
# closed properly; so there is a risk that blocking operations such
# as connect() hang on the server.
# we use non-blocking operations instead between the server and the device.
class DeviceToClientForwarder(NonBlockingSocket):

    def __init__(self, ev_loop, s_to_client, device_ip, device_port):
        self._ev_loop = ev_loop
        self._s_to_client = s_to_client
        self._send_buffer = b""
        self._label = f"Connection forwarder to {device_ip}:{device_port}"
        NonBlockingSocket.__init__(self, ev_loop,
                    device_ip, device_port, SOCKET_TO_DEVICE_TIMEOUT,
                    timeout_on_read=False)

    def on_connect(self):
        # "self" manages device -> client forwarding
        self.start_wait_read()
        # add a SocketForwarder to the event loop to handle the other way
        client_to_device_forwarder = SocketForwarder(self._s_to_client, self)
        self._ev_loop.register_listener(client_to_device_forwarder)

    def on_read_ready(self):
        try:
            buf = self.sock.recv(4096)
            if len(buf) == 0:
                # empty read, close
                return False
            self._s_to_client.sendall(buf)
        except Exception as e:
            print(f"{self._label}:", e)
            return False  # issue, close
        self.start_wait_read()

    # sendall is called by SocketForwarder above
    def sendall(self, buf):
        self._send_buffer += buf
        self.start_wait_write()

    def on_write_ready(self):
        try:
            length = self.sock.send(self._send_buffer)
            if length < len(self._send_buffer):
                self._send_buffer = self._send_buffer[length:]
                self.start_wait_write()
            else:
                self._send_buffer = b""
                self.start_wait_read()
        except Exception as e:
            print(f"{self._label}:", e)
            return False  # issue, close

    # nothing to do on timeout, close() is enough
    def on_connect_timeout(self):
        pass

    def on_write_timeout(self):
        pass

    def close(self):
        super().close()
        self._s_to_client.close()


class ExposeRedirect:

    def __init__(self, manager, server_port,
                 device_ip, device_port):
        self._ev_loop = manager.server.ev_loop
        self.server_port = server_port
        self.device_ip = device_ip
        self.device_port = device_port
        self.forwarder = None

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
        # we just instanciate DeviceToClientForwarder for now, the other way of the
        # connection will be managed after (and if) we manage to connect to the
        # device.
        self.forwarder = DeviceToClientForwarder(
                self._ev_loop, s_to_client, self.device_ip, self.device_port)
        self.forwarder.start_connect()

    def close(self):
        if self.forwarder is not None:
            self.forwarder.close()
        self._s.close()


class ExposeManager:

    def __init__(self, server):
        self.server = server
        self.redirects = {}  # { <server_port>: <ExposeRedirect object> }

    def cleanup(self):
        for redir in self.redirects.values():
            redir.close()
        self.redirects = {}

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
                "(device port 80 <-> server port 8088), or 'none'.\n"
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
                self.server.logs.platform_log("expose", line=logline, error=True)
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
