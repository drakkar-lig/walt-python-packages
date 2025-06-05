import errno
import itertools
import json
import numpy as np
import socket
import sys
from ipaddress import IPv4Address, ip_address, ip_network
from time import time, sleep
from typing import Union

from walt.common.evloop import POLL_OPS_READ, POLL_OPS_WRITE
from walt.common.formatting import COLUMNATE_SPACING
from walt.common.tools import set_close_on_exec

DEFAULT_JSON_HTTP_TIMEOUT = 10
JSON_HTTP_RETRIES = 3


def np_record_to_dict(record):
    return dict(zip(record.dtype.names,record))


def np_recarray_to_tuple_of_dicts(arr_src):
    if len(arr_src) == 0:
        return ()
    fields = arr_src.dtype.names
    num_fields, num_items = len(fields), arr_src.size
    arr = np.empty((2*num_fields, num_items), object)
    arr[0:2*num_fields:2] = np.array(fields).reshape((num_fields, 1))
    arr[1:2*num_fields:2] = [arr_src[f] for f in fields]
    arr = arr.T.reshape((num_items, num_fields, 2))
    return tuple(map(dict, arr))


def update_template(path, template_env):
    with open(path, "r+") as f:
        template_content = f.read()
        file_content = template_content % template_env
        f.seek(0)
        f.write(file_content)
        f.truncate()


def try_encode(s, encoding):
    if encoding is None:
        return False
    try:
        s.encode(encoding)
        return True
    except UnicodeError:
        return False


def format_node_models_list(node_models):
    from walt.server.autoglob import autoglob
    return autoglob(node_models)


# max number of file descriptors this process is allowed to open
SOFT_RLIMIT_NOFILE = 16384


def set_rlimits():
    import resource
    soft_limit, hard_limit = resource.getrlimit(resource.RLIMIT_NOFILE)
    resource.setrlimit(resource.RLIMIT_NOFILE, (SOFT_RLIMIT_NOFILE, hard_limit))


def get_server_ip() -> str:
    """Load the server IP address on walt-net from the configuration file."""
    from walt.server import conf

    return conf["network"]["walt-net"]["ip"].split("/")[0]


async def async_json_http_get(
    url, timeout=DEFAULT_JSON_HTTP_TIMEOUT, return_links=False, https_verify=True
):
    if https_verify:
        ssl_opt = None  # default setting of ssl option = verification enabled
    else:
        ssl_opt = False
    import aiohttp
    import asyncio
    for _ in range(JSON_HTTP_RETRIES):
        aiohttp_timeout = aiohttp.ClientTimeout(total=timeout)
        # note: trust_env=True ensure any HTTP[S]_PROXY env variable
        # (most probably in /etc/walt/server.env) is taken into account.
        session_kwargs = dict(timeout=aiohttp_timeout, trust_env=True)
        try:
            async with aiohttp.ClientSession(**session_kwargs) as session:
                async with session.get(url, ssl=ssl_opt) as response:
                    links = response.links
                    json_body = await response.json()
                    if return_links:
                        return json_body, links
                    else:
                        return json_body
        except asyncio.TimeoutError:
            await asyncio.sleep(1.0)
            continue
    raise asyncio.TimeoutError


async def async_gather_tasks(tasks):
    # make sure all asyncio tasks are run up to their result or exception
    import asyncio
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for res in results:
        if isinstance(res, Exception):
            raise res
    return results


async def async_merge_generators(*generators):
    from aiostream import stream
    merged_generator = stream.merge(*generators)
    async with merged_generator.stream() as streamer:
        async for item in streamer:
            yield item


def ip(ip_as_str):
    return ip_address(str(ip_as_str))


def net(net_as_str):
    return ip_network(str(net_as_str), strict=False)


def get_walt_subnet():
    from walt.server import conf

    return net(conf["network"]["walt-net"]["ip"])


def get_walt_adm_subnet():
    from walt.server import conf

    walt_adm_conf = conf["network"].get("walt-adm", None)
    if walt_adm_conf is None:
        return None
    else:
        return net(walt_adm_conf["ip"])


def ip_in_walt_network(input_ip):
    if input_ip is None:
        return False
    subnet = get_walt_subnet()
    return ip(input_ip) in subnet


def ip_in_walt_adm_network(input_ip):
    subnet = get_walt_adm_subnet()
    if subnet is None:
        return False
    else:
        return ip(input_ip) in subnet


def get_dns_servers() -> [Union[str, IPv4Address]]:
    local_server_is_dns_server = False
    dns_list = []
    with open("/etc/resolv.conf", "r") as f:
        for line in f:
            line = line.strip()
            if len(line) == 0:
                continue
            if line[0] == "#":
                continue
            if line.startswith("nameserver"):
                for dns_ip in line.split(" ")[1:]:
                    dns_ip = ip_address(dns_ip)
                    if dns_ip.version != 4:
                        # Not supported by dhcpd in our IPv4 configuration
                        continue
                    if dns_ip.is_loopback:
                        local_server_is_dns_server = True
                        continue
                    dns_list.append(dns_ip)
    # If walt server is a DNS server, and no other DNS is available, let the
    # walt nodes use it (but not with its localhost address!)
    if local_server_is_dns_server and len(dns_list) == 0:
        dns_list.append(get_server_ip())
    # Still no DNS server...  Hope that this one is reachable
    if len(dns_list) == 0:
        dns_list.append("8.8.8.8")
    return dns_list


def ensure_text_file_content(path, content):
    update_file = True
    if path.exists():
        if path.read_text() == content:
            update_file = False
    if update_file:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def add_image_repo(fullname):
    if fullname.startswith("walt/"):
        return "localhost/" + fullname
    else:
        return "docker.io/" + fullname


def get_registry_labels():
    from walt.server import conf

    return tuple(reg_info["label"] for reg_info in conf["registries"])


def get_clone_url_locations():
    return ("docker", "walt") + get_registry_labels()


# parse_date() handles the following example formats:
# - "2023-07-04T13:58:03.480332+02:00"
# - "2023-07-04T13:58:03.480332667+02:00"
# - "2023-07-04T13:58:03.480332667Z"
# - "2023-07-04T13:58:03Z"
# - "2023-07-04 13:58:03.480332 +0000 UTC"
# - "2023-07-04 13:58:03.480332 +0000"
# - "2023-07-04 13:58:03.480332 +00:00"
def parse_date(created_at):
    import re
    from datetime import datetime
    # add a space before the ending timezone offset
    created_at = re.sub(r"([+-][0-9][0-9:.]*)$", r" \1",  created_at)
    # interpret 'T' and 'Z'
    created_at = created_at.replace("T", " ").replace("Z", " +0000")
    # keep only the first 3 words (timezone is sometimes repeated as text)
    created_at = " ".join(created_at.split()[:3])
    # strptime does not support parsing nanosecond precision
    # remove last 3 decimals of this number
    created_at = re.sub(r"([0-9]{6})[0-9]*", r"\1", created_at)
    if '.' in created_at:
        return datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S.%f %z")
    else:
        return datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S %z")


def np_str_pattern(pattern):
    analysis = ()
    while True:
        parts = pattern.split("%(", maxsplit=1)
        analysis += (parts[0],)
        if len(parts) == 1:
            break
        field, pattern = parts[1].split(")s", maxsplit=1)
        analysis += (field,)
    return analysis


def np_apply_str_pattern(pattern, data):
    result = ""
    while True:
        result += pattern[0]
        if len(pattern) == 1:
            return result
        field, pattern = pattern[1], pattern[2:]
        result += data[field]


def np_columnate(tabular_data, shrink_empty_cols=False, align=None):
    if len(tabular_data) == 0:
        return ""
    # align cell content on the left if not specified
    if align is None:
        align = "<" * len(tabular_data[0])
    align = np.array(list(align))
    # turn tabular_data into a 2-dimensions str array
    col_names = np.array(tabular_data.dtype.names)
    data = np.concatenate(
            [tabular_data[field].astype(str) for field in col_names])
    data = data.reshape(len(col_names), len(tabular_data))
    # sanitize
    data[data == 'None'] = ""
    # print col name "compatibility:tuple" as "compatibility"
    # print col name "in_use" as "in-use"
    pretty_col_names = np.char.partition(col_names, ":")[:,0]
    pretty_col_names = np.char.replace(pretty_col_names, "_", "-")
    # add col name and sep lines (empty for now)
    data = np.insert(data, 0, "", axis=1)
    data = np.insert(data, 0, pretty_col_names, axis=1)
    # compute lengths
    lengths = np.char.str_len(data)
    # remove empty cols
    if shrink_empty_cols:
        max_data_lengths = np.max(lengths[:,2:], axis=1)
        if not max_data_lengths.all():
            # at least one column is empty
            cols_mask = (max_data_lengths > 0)
            lengths = lengths[cols_mask]
            data = data[cols_mask]
            col_names = col_names[cols_mask]
            align = align[cols_mask]
    # some steps below may add 3 more chars at most to
    # each cell (two spaces and a carriage return)
    # so let's define a larger data type
    cols_width = np.max(lengths, axis=1)
    max_cell_width = cols_width.max() + COLUMNATE_SPACING + 1
    data = data.T.astype(f"<U{max_cell_width}")
    # set header sep line
    data[1] = np.char.ljust(data[1], cols_width, "-")
    # align
    cols_align_left = (align == "<")
    if cols_align_left.any():
        data[:,cols_align_left] = np.char.ljust(
                data[:,cols_align_left], cols_width[cols_align_left])
    cols_align_right = (align == ">")
    if cols_align_right.any():
        data[:,cols_align_right] = np.char.rjust(
                data[:,cols_align_right], cols_width[cols_align_right])
    # separate columns with two spaces
    spaces = COLUMNATE_SPACING * " "
    data[:,1:] = np.char.add(spaces, data[:,1:])
    # finalize formatting
    data[:-1,-1] = np.char.add(data[:-1,-1], "\n")
    return "".join(data.flat)


def get_rpi_foundation_mac_vendor_ids(zero_padded=True):
    if zero_padded:
        return ("28:cd:c1", "b8:27:eb", "d8:3a:dd", "dc:a6:32", "e4:5f:01",
                "2c:cf:67", "88:a2:9e")
    else:
        return ("28:cd:c1", "b8:27:eb", "d8:3a:dd", "dc:a6:32", "e4:5f:1",
                "2c:cf:67", "88:a2:9e")


def non_blocking_connect(sock, ip, port):
    try:
        sock.connect((ip, port))
    except BlockingIOError as e:
        if e.errno == errno.EINPROGRESS:
            pass  # ok, ignore
        else:
            raise  # unexpected, raise


class NonBlockingSocket:

    class STATUS:
        INIT = 0
        CONNECTING = 1
        WAITING_READ = 2
        WAITING_WRITE = 3
        CLOSED = 4

    def __init__(self, ev_loop, ip, port, timeout_secs=15,
                 timeout_on_connect=True, timeout_on_read=True,
                 timeout_on_write=True):
        self.ev_loop = ev_loop
        self.ip = ip
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setblocking(False)  # should not block
        set_close_on_exec(self.sock, True)
        self.status = NonBlockingSocket.STATUS.INIT
        self.timeout_secs = timeout_secs
        self.timeout_ids = itertools.count()
        self.timeout_id = -1
        self.timeout_on_connect = timeout_on_connect
        self.timeout_on_read = timeout_on_read
        self.timeout_on_write = timeout_on_write

    def start_timeout(self):
        # we set a timeout on the event loop
        self.timeout_id = next(self.timeout_ids)
        timeout_at = time() + self.timeout_secs
        self.ev_loop.plan_event(ts=timeout_at, callback=self.on_timeout,
                                timeout_id = self.timeout_id)

    def start_connect(self):
        # connect call should not block, thus we use non-blocking mode
        # and let the event loop recall us when we can *write* on the socket
        non_blocking_connect(self.sock, self.ip, self.port)
        self.status = NonBlockingSocket.STATUS.CONNECTING
        self.ev_loop.register_listener(self, POLL_OPS_WRITE)
        if self.timeout_on_connect:
            self.start_timeout()

    def start_wait_read(self):
        self.status = NonBlockingSocket.STATUS.WAITING_READ
        self.ev_loop.update_listener(self, POLL_OPS_READ)
        if self.timeout_on_read:
            self.start_timeout()

    def start_wait_write(self):
        self.status = NonBlockingSocket.STATUS.WAITING_WRITE
        self.ev_loop.update_listener(self, POLL_OPS_WRITE)
        if self.timeout_on_write:
            self.start_timeout()

    def on_timeout(self, timeout_id):
        # ignore obsolete timeouts
        if self.timeout_id != timeout_id:
            return
        saved_status = self.status
        # ev_loop will call close(), setting status to CLOSED
        self.ev_loop.remove_listener(self)
        if saved_status == NonBlockingSocket.STATUS.CONNECTING:
            self.on_connect_timeout()
        elif saved_status == NonBlockingSocket.STATUS.WAITING_READ:
            self.on_read_timeout()
        elif saved_status == NonBlockingSocket.STATUS.WAITING_WRITE:
            self.on_write_timeout()

    def handle_event(self, ts):
        # the event loop detected an event for us
        self.timeout_id = -1
        if self.status == NonBlockingSocket.STATUS.CONNECTING:
            return self.on_connect()
        elif self.status == NonBlockingSocket.STATUS.WAITING_READ:
            return self.on_read_ready()
        elif self.status == NonBlockingSocket.STATUS.WAITING_WRITE:
            return self.on_write_ready()
        elif self.status == NonBlockingSocket.STATUS.CLOSED:
            return False
        else:
            raise Exception(f"Unexpected status {self.status}")

    def send(self, *args, **kwargs):
        return self.sock.send(*args, **kwargs)

    def recv(self, *args, **kwargs):
        return self.sock.recv(*args, **kwargs)

    # let the event loop know what we are reading on
    def fileno(self):
        return self.sock.fileno()

    def close(self):
        if self.sock is not None:
            self.sock.close()
            self.sock = None
        self.status = NonBlockingSocket.STATUS.CLOSED

    def on_connect_timeout(self):
        raise NotImplementedError

    def on_read_timeout(self):
        raise NotImplementedError

    def on_write_timeout(self):
        raise NotImplementedError

    def on_connect(self):
        raise NotImplementedError

    def on_read_ready(self):
        raise NotImplementedError

    def on_write_ready(self):
        raise NotImplementedError

    def __del__(self):
        if not self.status == NonBlockingSocket.STATUS.CLOSED:
            print(f"{self} was not closed when garbage collected.", file=sys.stderr)


def convert_query_param_value(value, value_type):
    if value_type != str:
        try:
            value = json.loads(value)
            value = value_type(value)
        except Exception:
            return (False, {
                "code": 400,
                "message": (
                    f"cannot interpret '{value}' as a '{value_type.__name__}'.")
            })
    return (True, value)


def filter_items_with_query_params(items, field_types, query_params):
    for field, value in query_params.items():
        field_type = field_types.get(field, None)
        if field_type is None:
            return (False, {
                "code": 400,
                "message": f"'{field}' is not a valid filtering field."
            })
        if len(value) == 0:
            continue
        res = convert_query_param_value(value, field_type)
        if not res[0]:
            return (False, res[1])
        value = res[1]
        items = items[items[field] == value]
    return (True, items)


def get_podman_client():
    from walt.server.const import PODMAN_API_SOCK_PATH
    from podman import PodmanClient

    c = PodmanClient(base_url=f"http+unix://{PODMAN_API_SOCK_PATH}")
    # When an HTTP_PROXY is defined, requests & urllib3 libraries
    # wrongly redirect there although it is a UNIX socket!
    # and the NO_PROXY env seems not taken into account.
    # The following line works around this issue.
    c.api.trust_env = False
    return c


class NetworkBuf:
    def __init__(self, s):
        self._s = s
        self._buf = b''
    def read(self, length):
        while len(self._buf) < length:
            chunk = self._s.recv(4096)
            if len(chunk) == 0:
                raise Exception("Empty read")
            self._buf += chunk
        res = self._buf[:length]
        self._buf = self._buf[length:]
        return res
    def write(self, buf):
        while (len(buf) > 0):
            length = self._s.send(buf)
            buf = buf[length:]
    def sendfile(self, f, offset, length):
        self._s.sendfile(f, offset, length)
    def pending_buflen(self):
        return len(self._buf)
    def fileno(self):
        return self._s.fileno()
    def close(self):
        self._s.close()


def NetworkMsg(fmt, *static_args):
    import struct
    length = struct.calcsize(fmt)
    class NetworkMsgCls:
        @staticmethod
        def read(netbuf):
            buf = netbuf.read(length)
            t = struct.unpack(fmt, buf)
            if len(t) == 1:
                return t[0]
            else:
                return t
        @classmethod
        def format(cls, *args):
            return struct.pack(fmt, *(static_args + args))
        @classmethod
        def write(cls, netbuf, *args):
            buf = cls.format(*args)
            netbuf.write(buf)
    return NetworkMsgCls


class TTLCache:
    def __init__(self):
        self._cache = {}
    def get(self, item):
        if item in self._cache:
            deadline, delay, value = self._cache.pop(item)
            if deadline < time():
                # obsolete
                return (False,)
            else:
                # still valid
                deadline = time() + delay
                self._cache[item] = (deadline, delay, value)
                return (True, value)
        else:
            return (False,)
    def save(self, item, value, delay):
        deadline = time() + delay
        self._cache[item] = (deadline, delay, value)


def ttl_cache(delay):
    def ttl_cache_decorator(f):
        cache = TTLCache()
        def decorated(*args, **kwargs):
            import pickle
            h = pickle.dumps((args, kwargs))
            cache_result = cache.get(h)
            if cache_result[0] is True:
                return cache_result[1]
            else:
                result = f(*args, **kwargs)
                cache.save(h, result, delay)
                return result
        return decorated
    return ttl_cache_decorator


def wait_message_read():
    print(" " * 71 + "]\r[", end="")
    sys.stdout.flush()
    for i in range(70):
        print("*", end="")
        sys.stdout.flush()
        sleep(0.28)
    print("\r" + " " * 72 + "\r", end="")
    sys.stdout.flush()
