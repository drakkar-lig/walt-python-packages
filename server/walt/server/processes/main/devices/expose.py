import itertools
import re
import socket
from collections import defaultdict
from pathlib import Path
from walt.common.tcp import server_socket
from walt.server.tools import NonBlockingSocket

SOCKET_TO_DEVICE_TIMEOUT = 2

MSG_WRONG_EXPOSE_VALUE = """\
Failed: '{setting_value}' is not a valid value for option 'expose'.
        Use for example:
        -> '80:8088' (device port 80 <-> server port 8088)
        -> '80' (device port 80 <-> server port automatically chosen)
        -> '80:8080,443:8443' (2 ports exposed)
        -> '80,443' (2 ports exposed, server ports automatically chosen)
        -> or 'none'.
        See `walt help show device-expose` for more info.
"""

DYN_PORTS_BOUNDS_FILE = Path("/proc/sys/net/ipv4/ip_local_port_range")


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
        self.dyn_ports_low_bound = self._get_dyn_ports_low_bound()

    def _get_dyn_ports_low_bound(self):
        return int(DYN_PORTS_BOUNDS_FILE.read_text().split()[0])

    def cleanup(self):
        for redir in self.redirects.values():
            redir.close()
        self.redirects = {}

    def parse_expose_setting_value(self, setting_value):
        if setting_value != "none" and \
            re.match(r"^\d+(:\d+)?(,\d+(:\d+)?)*$", setting_value) is None:
            return (False,)
        _explicit_redirects, _implicit_redirects = [], []
        if setting_value != "none":
            for redirect in setting_value.split(","):
                if ':' in redirect:
                    device_port_s, server_port_s = redirect.split(':')
                    _explicit_redirects.append((int(device_port_s),
                                                int(server_port_s)))
                else:
                    _implicit_redirects.append(int(redirect))
        return (True, _explicit_redirects, _implicit_redirects)

    def check_expose_setting_value(self, requester, devices_ip, setting_value):
        parsed = self.parse_expose_setting_value(setting_value)
        if not parsed[0]:
            requester.stderr.write(MSG_WRONG_EXPOSE_VALUE.replace(
                    "{setting_value}", setting_value))
            return False
        explicit_redirects, implicit_redirects = parsed[1], parsed[2]
        all_device_ports = implicit_redirects.copy()
        if len(explicit_redirects) > 0:
            if len(devices_ip) > 1:
                requester.stderr.write(
                      "Failed: cannot expose the same server port for "
                      "several devices.\n")
                return False
            device_ports, server_ports = tuple(zip(*explicit_redirects))
            if len(set(server_ports)) < len(explicit_redirects):
                requester.stderr.write(
                      "Failed: cannot use several times the same server "
                      "port number.\n"
                )
                return False
            for server_port in server_ports:
                if server_port >= self.dyn_ports_low_bound:
                    port_max = self.dyn_ports_low_bound - 1
                    requester.stderr.write(
                          f"Failed: port {server_port} is too high "
                          f"(max is {port_max}).\n"
                    )
                    return False
            for device_port, server_port in explicit_redirects:
                redir = self.redirects.get(server_port, None)
                if redir is None:
                    # first time this server port is used,
                    # check if we can bind it
                    check, err = self.check_bind_port(server_port)
                    if not check:
                        requester.stderr.write(
                                "Failed: cannot use server port "
                                f"'{server_port}': {err}.\n"
                        )
                        return False
                else:
                    # this port is already in use for a redirect, check if
                    # this is for one of the devices we are currently
                    # configuring.
                    if redir.device_ip not in devices_ip:
                        requester.stderr.write(
                          f"Failed: server port '{server_port}' is already "
                          " used for another redirect.\n"
                        )
                        return False
            all_device_ports += list(device_ports)
        if len(set(all_device_ports)) < len(all_device_ports):
            requester.stderr.write(
                  "Failed: cannot use several times the same device port "
                  "number.\n"
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

    def _port_would_work(self, server_port,
                         wrong_server_ports, old_server_ports):
        if server_port >= self.dyn_ports_low_bound:
            return False
        if server_port in wrong_server_ports:
            return False  # in use for something else or tested with failure
        if server_port in old_server_ports:
            # this port was present in the previous setting,
            # no need to test, we now it works
            return True
        check, _ = self.check_bind_port(server_port)
        if check:
            return True  # it works
        else:
            wrong_server_ports.add(server_port)
            return False

    def choose_server_port(self, device_port, proposed_offset,
                           wrong_server_ports, old_server_ports):
        # 1st choice, check with the proposed offset
        server_port = device_port + proposed_offset
        if self._port_would_work(server_port,
                                 wrong_server_ports, old_server_ports):
            return server_port
        # 2nd choice, check with an offset multiple of 1000,
        # then 100, then 10, then 1
        for multiple in (1000, 100, 10, 1):
            for offset in itertools.count(4000, multiple):
                server_port = device_port + offset
                if self._port_would_work(server_port,
                         wrong_server_ports, old_server_ports):
                    return server_port
        raise Exception("Could not find a free TCP port!")

    def apply(self, requester, devices_ip, setting_value):
        # previous settings (explicit form)
        old_redirects = set()
        new_redirects_per_ip = defaultdict(list)
        offsets_per_ip = {}
        wrong_server_ports = set()
        old_server_ports = set()
        for redir in self.redirects.values():
            offsets_per_ip[redir.device_ip] = (
                    redir.server_port - redir.device_port)
            if redir.device_ip in devices_ip:
                old_redirects.add((redir.device_ip,
                                   redir.device_port, redir.server_port))
                old_server_ports.add(redir.server_port)
            else:
                wrong_server_ports.add(redir.server_port)  # taken
        # parse new setting
        parsed = self.parse_expose_setting_value(setting_value)
        assert parsed[0] is True
        # explicit form: <device-port>:<server-port>
        explicit_redirects = parsed[1]
        for dev_ip in devices_ip:
            for dev_p, serv_p in explicit_redirects:
                new_redirects.add((dev_ip, dev_p, serv_p))
                new_redirects_per_ip[dev_ip].append((dev_p, serv_p))
                wrong_server_ports.add(serv_p)  # taken
        # implicit form: <device-port>
        # (we will have to select a server port automatically)
        implicit_redirects = parsed[2]
        for dev_ip in devices_ip:
            proposed_offset = offsets_per_ip.get(dev_ip)
            for dev_p in implicit_redirects:
                serv_p = self.choose_server_port(
                    dev_p, proposed_offset,
                    wrong_server_ports, old_server_ports)
                wrong_server_ports.add(serv_p)  # taken
                new_redirects.add((dev_ip, dev_p, serv_p))
                new_redirects_per_ip[dev_ip].append((dev_p, serv_p))
                proposed_offset = serv_p - dev_p
        # stop old redirects
        for dev_ip, dev_p, serv_p in old_redirects - new_redirects:
            redir = self.redirects.pop(serv_p)
            redir.close()
        # create new redirects
        for dev_ip, dev_p, serv_p in new_redirects - old_redirects:
            self.add_redirect(requester, serv_p, dev_ip, dev_p)
        # return the fully resolved redirects per ip
        result = {}
        if setting_value == "none":
            for ip in devices_ip:
                result[ip] = "none"
        else:
            for ip, ip_redirects in new_redirects_per_ip.items():
                result[ip] = ",".join(
                    f"{dev_p}:{serv_p}"
                    for dev_p, serv_p in sorted(ip_redirects))
        return result

    def restore(self):
        for row in self.server.db.execute("""\
                SELECT ip, conf->'expose' as setting_value FROM devices
                WHERE conf->'expose' IS NOT NULL; """):
            parsed = self.parse_expose_setting_value(row.setting_value)
            assert parsed[0] is True
            # the db should not contain any implicit expose configurations
            assert len(parsed[2]) == 0
            redirects = parsed[1]
            for device_port, server_port in redirects:
                self.add_redirect(None, server_port, row.ip, device_port)

    def get_web_links_info(self):
        result = {}
        for row in self.server.db.execute("""\
                SELECT name, type, conf->>'expose' as setting_value
                FROM devices
                WHERE conf->>'expose' != 'none';"""):

            parsed = self.parse_expose_setting_value(row.setting_value)
            assert parsed[0] is True
            dev_links = dict(parsed[1])
            result[row.name] = (row.type, dev_links)
        return result
