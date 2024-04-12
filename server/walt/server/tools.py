import numpy as np
from ipaddress import IPv4Address, ip_address, ip_network
from typing import Union

from walt.common.formatting import COLUMNATE_SPACING

DEFAULT_JSON_HTTP_TIMEOUT = 10


def np_record_to_dict(record):
    return dict(zip(record.dtype.names,record))


def np_recarray_to_tuple_of_dicts(arr_src):
    if len(arr_src) == 0:
        return ()
    fields = arr_src.dtype.names
    num_fields, num_items = len(fields), arr_src.size
    arr = np.empty((2*num_fields, num_items), object)
    col = 0
    for f in fields:
        arr[col] = f
        arr[col+1] = arr_src[f]
        col += 2
    arr = arr.T.reshape((num_items, num_fields, 2))
    return tuple(dict(i) for i in arr)


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


# parse_date() handles the following example formats:
# - "2023-07-04T13:58:03.480332+02:00"
# - "2023-07-04T13:58:03.480332667+02:00"
# - "2023-07-04T13:58:03.480332667Z"
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
    return datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S.%f %z")


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
    # add col name and sep lines (empty for now)
    data = np.insert(data, 0, "", axis=1)
    data = np.insert(data, 0, col_names, axis=1)
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
