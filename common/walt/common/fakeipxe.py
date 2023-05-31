#!/usr/bin/env python
import code
import os.path
import shlex
import sys
import tempfile
import time
from collections import namedtuple
from urllib.parse import urlparse

import requests
from walt.common.constants import WALT_SERVER_TCP_PORT
from walt.common.tcp import Requests, client_sock_file, write_pickle

OS_ENCODING = sys.stdout.encoding

SHELL_BANNER = """\
[fake-ipxe] Entering interactive python shell.
[fake-ipxe] You can print variables such as ip, mac, etc.\
"""

# Notes:
# fake TFTP is implemented by using a direct TCP connection
# to the server API.
# HTTP is implemented by using a real HTTP connection to
# walt-server-httpd. Daemon walt-server-httpd then itself
# performs a direct TCP connection to the server API.
#
# The server API handles the requests in a synchronous way,
# whereas walt-server-httpd can handle them in parallel.
# Thus in a network with several distant nodes (cf. vpn or kexec)
# and a high latency, HTTP method will probably be faster,
# because the synchronous part is handled on localhost.


def fake_tftp_read(env, abs_path):
    # connect to server
    f = client_sock_file(env["next-server"], WALT_SERVER_TCP_PORT)
    try:
        # send the request id
        Requests.send_id(f, Requests.REQ_FAKE_TFTP_GET)
        # wait for the READY message from the server
        f.readline()
        # write the parameters
        write_pickle(dict(node_mac=env["mac"], path=abs_path), f)
        # receive status
        status = f.readline().decode("UTF-8").strip()
        if status == "OK":
            # read size
            size = int(f.readline().strip())
            print(abs_path, size)
            # receive content
            content = b""
            while len(content) < size:
                content += f.read(size - len(content))
        else:
            content = None
        # return
        print(abs_path + " " + status)
        return content
    finally:
        # close file
        f.close()


def http_read(url):
    try:
        res = requests.get(url)
        if res.ok:
            print(url, "OK")
            return res.content
        else:
            print(url, res.reason)
            return None
    except Exception:
        print(url, "Connection failed")
        return None


CanonicalPathBase = namedtuple("CanonicalPathBase", ["proto", "abs_path"])


class CanonicalPath(CanonicalPathBase):
    @classmethod
    def from_url(cls, env, url):
        url_info = urlparse(url)
        path = url_info.path
        if url_info.scheme == "http":
            return cls("http", path)
        elif url_info.scheme == "tftp":
            return cls("tftp", path)
        elif url_info.scheme == "":
            if path[0] == "/":  # absolute path
                return cls("tftp", path)
            else:
                # path relative to current dir
                cur_dir = remote_curdir(env)
                abs_path = os.path.join(cur_dir.abs_path, path)
                return cls(cur_dir.proto, abs_path)
        else:
            raise NotImplementedError(
                "[fake-ipxe] Unknown protocol: " + url_info.scheme
            )

    def to_url(self, env):
        url = self.proto + "://" + env["next-server"] + self.abs_path
        # virtual nodes are running on the server, so the peer IP
        # detected on web server side will not match the node IP.
        # so we specify this ip as an URL parameter.
        if self.proto == "http":
            url += "?node_ip=" + env["ip"]
        return url

    def read(self, env):
        url = self.to_url(env)
        if self.proto == "http":
            return http_read(url)
        else:  # tftp
            return fake_tftp_read(env, self.abs_path)

    def dirname(self):
        return CanonicalPath(self.proto, os.path.dirname(self.abs_path))


def remote_curdir(env):
    return env["REMOTEDIRSTACK"][-1]  # top of the stack


def remote_cd(env, canon_path):
    env["REMOTEDIRSTACK"].append(canon_path)


def remote_revert_cd(env):
    env["REMOTEDIRSTACK"] = env["REMOTEDIRSTACK"][:-1]  # pop


def execute_line(env, line):
    # if flag 'should-boot' was just set to True and False was returned in an
    # attempt to stop the process, we might still be called again to handle
    # the right part of a current 'or' condition.
    if env["should-boot"]:
        return False  # stop!!
    # strip comments
    line = line.split("#")[0]
    line = line.strip()
    # handle empty line
    if line == "":
        return True
    # parse and / or conditions
    cond = None
    and_conditions = line.rsplit("&&", 1)
    or_conditions = line.rsplit("||", 1)
    if len(and_conditions) + len(or_conditions) == 4:
        if len(and_conditions[1]) < len(or_conditions[1]):
            cond = "and"
        else:
            cond = "or"
    elif len(and_conditions) == 2:
        cond = "and"
    elif len(or_conditions) == 2:
        cond = "or"
    if cond == "and":
        return execute_line(env, and_conditions[0]) and execute_line(
            env, and_conditions[1]
        )
    if cond == "or":
        return execute_line(env, or_conditions[0]) or execute_line(
            env, or_conditions[1]
        )
    # tokenize
    words = shlex.split(line)
    # replace variables
    words_copy = words[:]
    words = []
    for word in words_copy:
        while True:
            splitted = word.split("${", 1)
            if len(splitted) == 1:
                break
            var_name, ending = splitted[1].split("}", 1)
            word = splitted[0] + env.get(var_name, "") + ending
        words.append(word)
    # handle "set" directive
    if words[0] == "set":
        if len(words) == 2:
            env[words[1]] = ""
        else:
            env[words[1]] = " ".join(words[2:])
        return True
    # handle "echo" directive
    if words[0] == "echo":
        print(" ".join(words[1:]))
        return True
    if words[0] == "shell":
        code.interact(banner=SHELL_BANNER, local=env)
        return True
    # handle "chain" directive
    if words[0] == "chain":
        path = CanonicalPath.from_url(env, " ".join(words[1:]))
        content = path.read(env)
        if content is None:
            return False
        # when executing a script, relative paths will be interpreted
        # as being relative to the path of the script itself
        remote_cd(env, path.dirname())
        for line in content.decode(OS_ENCODING).splitlines():
            if not execute_line(env, line):
                return False
        remote_revert_cd(env)
        return True
    # handle "imgfree" directive
    if words[0] == "imgfree":
        return True  # nothing to do here
    # handle "initrd" directive
    if words[0] == "initrd":
        initrd_path = CanonicalPath.from_url(env, " ".join(words[1:]))
        content = initrd_path.read(env)
        if content is None:
            return False
        initrd_copy = env["TMPDIR"] + "/initrd"
        with open(initrd_copy, "wb") as f:
            f.write(content)
        env["boot-initrd"] = initrd_copy
        return True
    # handle "kernel" and "boot" directives
    if words[0] in ("boot", "kernel"):
        if len(words) > 1:
            kernel_path = CanonicalPath.from_url(env, words[1])
            kernel_cmdline = " ".join(words[2:])
            content = kernel_path.read(env)
            if content is None:
                return False
            kernel_copy = env["TMPDIR"] + "/kernel"
            with open(kernel_copy, "wb") as f:
                f.write(content)
            env["boot-kernel"] = kernel_copy
            env["boot-kernel-cmdline"] = kernel_cmdline
        if words[0] == "boot":
            env["should-boot"] = True
            return False  # stop
        else:
            return True
    # handle "sleep" directive
    if words[0] == "sleep":
        delay = int(words[1])
        time.sleep(delay)
        return True
    # handle "reboot" directive
    if words[0] == "reboot":
        return False  # stop
    # unknown directive!
    raise NotImplementedError(
        '[fake-ipxe] Unknown directive "' + words[0] + '". Aborted.'
    )


def ipxe_boot(env):
    print("[fake-ipxe] note: this is not the real iPXE bootloader!")
    print("[fake-ipxe] note: support is limited to a basic command set.")
    env["should-boot"] = False
    with tempfile.TemporaryDirectory() as TMPDIR:
        net_setup_func = env["fake-network-setup"]
        with net_setup_func(env) as setup_result:
            if setup_result is True:
                # update env with netboot / ipxe specific info
                env.update(
                    {
                        "TMPDIR": TMPDIR,
                        "REMOTEDIRSTACK": ["/"],
                        "name": env["hostname"],
                        "mac:hexhyp": env["mac"].replace(":", "-"),
                        "next-server": env["server_ip"],
                    }
                )
                # start ipxe emulated netboot
                remote_cd(env, CanonicalPath("tftp", "/"))  # default dir
                execute_line(env, "chain /start.ipxe")
        # note: we just left the with context because we no
        # longer need the temporary network setup that was
        # possibly established.
        if env["should-boot"]:
            boot_function = env["boot-function"]
            boot_function(env)
