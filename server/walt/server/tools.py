import asyncio
import pdb
import pickle
import resource
import sys
from collections import namedtuple
from ipaddress import IPv4Address, ip_address, ip_network
from multiprocessing import current_process
from typing import Union

import aiohttp
from aiostream import stream
from walt.server.autoglob import autoglob

DEFAULT_JSON_HTTP_TIMEOUT = 10


def fix_pdb():
    # monkey patch pdb for usage in a subprocess
    pdb.SavedPdb = pdb.Pdb

    class BetterPdb(pdb.SavedPdb):
        def interaction(self, *args, **kwargs):
            try:
                self.prompt = f"(Pdb {current_process().name}) "
                sys.stdin = open("/dev/stdin")
                pdb.SavedPdb.interaction(self, *args, **kwargs)
            finally:
                sys.stdin = sys.__stdin__

    pdb.Pdb = BetterPdb


# wrapper to make a named tuple serializable using pickle
# even if it was built from a local class
class SerializableNT:
    def __init__(self, nt=None):
        self.nt = nt

    def __getstate__(self):
        return self.nt._asdict()

    def __setstate__(self, d):
        self.nt = to_named_tuple(d)

    def __getattr__(self, attr):
        return getattr(self.nt, attr)

    def __iter__(self):
        return iter(self.nt)

    def __len__(self):
        return len(self.nt)

    def __getitem__(self, i):
        return self.nt[i]

    def __lt__(self, other):
        return self.nt < other

    def __gt__(self, other):
        return self.nt > other

    def __eq__(self, other):
        return self.nt == other

    @staticmethod
    def get_factory(nt_cls):
        def create(*args, **kwargs):
            nt = nt_cls(*args, **kwargs)
            return SerializableNT(nt)

        return create


nt_index = 0
nt_classes = {}


def build_named_tuple_cls(d):
    global nt_index
    code = pickle.dumps(tuple(d.keys()))
    if code not in nt_classes:
        base = namedtuple("NamedTuple_%d" % nt_index, list(d.keys()))

        class NT(base):
            def update(self, **kwargs):
                d = self._asdict()
                d.update(**kwargs)
                return to_named_tuple(d)

        nt_classes[code] = SerializableNT.get_factory(NT)
        nt_index += 1
    return nt_classes[code]


def to_named_tuple(d):
    return build_named_tuple_cls(d)(**d)


def merge_named_tuples(nt1, nt2):
    d = nt1._asdict()
    d.update(nt2._asdict())
    return to_named_tuple(d)


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
    return autoglob(node_models)


# max number of file descriptors this process is allowed to open
SOFT_RLIMIT_NOFILE = 16384


def set_rlimits():
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
    timeout = aiohttp.ClientTimeout(total=timeout)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, ssl=ssl_opt) as response:
            links = response.links
            json_body = await response.json()
            if return_links:
                return json_body, links
            else:
                return json_body


async def async_gather_tasks(tasks):
    # make sure all asyncio tasks are run up to their result or exception
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for res in results:
        if isinstance(res, Exception):
            raise res
    return results


async def async_merge_generators(*generators):
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


def get_registry_info(label):
    from walt.server import conf

    for reg_info in conf["registries"]:
        if reg_info["label"] == label:
            return reg_info


def get_registry_labels():
    from walt.server import conf

    return tuple(reg_info["label"] for reg_info in conf["registries"])


def get_clone_url_locations():
    return ("docker", "walt") + get_registry_labels()
