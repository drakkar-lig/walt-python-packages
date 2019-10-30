#!/usr/bin/env python
import sys, subprocess, tempfile, shlex, time, os.path
from walt.common.tcp import write_pickle, client_sock_file, \
                            Requests
from walt.common.constants import WALT_SERVER_TCP_PORT

OS_ENCODING = sys.stdout.encoding

def fake_tftp_read(env, path):
    # connect to server
    f = client_sock_file(env['next-server'], WALT_SERVER_TCP_PORT)
    # send the request id
    Requests.send_id(f, Requests.REQ_FAKE_TFTP_GET)
    # wait for the READY message from the server
    f.readline()
    # write the parameters
    write_pickle(dict(
            node_mac=env['mac'],
            path=remote_absname(env, path)), f)
    # receive status
    status = f.readline().decode('UTF-8').strip()
    if status == 'OK':
        # read size
        size = int(f.readline().strip())
        print(path, size)
        # receive content
        content = b''
        while len(content) < size:
            content += f.read(size - len(content))
    else:
        content = None
    # close file and return
    f.close()
    print(path + " " + status)
    return content

def remote_curdir(env):
    return env['REMOTEDIRSTACK'][-1]    # top of the stack

def remote_absname(env, path):
    if path[0] == '/':
        return path     # already absolute
    else:
        return os.path.join(remote_curdir(env), path)

def remote_dirname(env, path):
    if path[0] != '/':
        path = remote_absname(env, path)
    return os.path.dirname(path)

def remote_cd(env, path):
    env['REMOTEDIRSTACK'].append(remote_absname(env, path))

def remote_revert_cd(env):
    env['REMOTEDIRSTACK'] = env['REMOTEDIRSTACK'][:-1]  # pop

def execute_line(env, line):
    line = line.strip()
    # pass comments
    if line.startswith('#'):
        return True
    # handle empty line
    if line == '':
        return True
    # parse and / or conditions
    cond = None
    and_conditions = line.rsplit('&&', 1)
    or_conditions = line.rsplit('||', 1)
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
        return execute_line(env, and_conditions[0]) and execute_line(env, and_conditions[1])
    if cond == "or":
        return execute_line(env, or_conditions[0]) or execute_line(env, or_conditions[1])
    # tokenize
    words = shlex.split(line)
    # replace variables
    words_copy = words[:]
    words = []
    for word in words_copy:
        while True:
            splitted = word.split('${', 1)
            if len(splitted) == 1:
                break
            var_name, ending = splitted[1].split('}', 1)
            word = splitted[0] + env[var_name] + ending
        words.append(word)
    # handle "set" directive
    if words[0] == 'set':
        if len(words) == 2:
            env[words[1]] = ''
        else:
            env[words[1]] = ' '.join(words[2:])
        return True
    # handle "echo" directive
    if words[0] == 'echo':
        print(' '.join(words[1:]))
        return True
    # handle "chain" directive
    if words[0] == 'chain':
        path = ' '.join(words[1:])
        content = fake_tftp_read(env, path)
        if content is None:
            return False
        # when executing a script, relative paths will be interpreted
        # as being relative to the path of the script itself
        remote_cd(env, remote_dirname(env, path))
        for line in content.decode(OS_ENCODING).splitlines():
            if not execute_line(env, line):
                return False
        remote_revert_cd(env)
        return True
    # handle "imgfree" directive
    if words[0] == 'imgfree':
        return True     # nothing to do here
    # handle "initrd" directive
    if words[0] == 'initrd':
        initrd_path = ' '.join(words[1:])
        content = fake_tftp_read(env, initrd_path)
        if content is None:
            return False
        initrd_copy = env['TMPDIR'] + '/initrd'
        with open(initrd_copy, 'wb') as f:
            f.write(content)
        env["qemu-args"] += " -initrd " + initrd_copy
        return True
    # handle "kernel" and "boot" directives
    if words[0] in ('boot', 'kernel'):
        if len(words) > 1:
            kernel_path = words[1]
            kernel_cmdline = " ".join(words[2:])
            content = fake_tftp_read(env, kernel_path)
            if content is None:
                return False
            kernel_copy = env['TMPDIR'] + '/kernel'
            with open(kernel_copy, 'wb') as f:
                f.write(content)
            env["qemu-args"] += " -kernel " + kernel_copy
            env["qemu-args"] += " -append '" + kernel_cmdline + "'"
        if words[0] == 'boot':
            env["qemu-cmd"] = env["qemu-args"] % env
            return False    # reboot when it exits
        else:
            return True
    # handle "sleep" directive
    if words[0] == 'sleep':
        delay = int(words[1])
        time.sleep(delay)
        return True
    # handle "reboot" directive
    if words[0] == 'reboot':
        return False
    # unknown directive!
    raise NotImplementedError('Unknown directive "' + words[0] + '". Aborted.')

def ipxe_boot(env):
    with tempfile.TemporaryDirectory() as TMPDIR:
        net_setup_func = env['fake-network-setup']
        with net_setup_func(env) as setup_result:
            if setup_result is True:
                # update env with netboot / ipxe specific info
                env.update({
                    'TMPDIR': TMPDIR,
                    'REMOTEDIRSTACK': ['/'],
                    'name': env['hostname'],
                    'mac:hexhyp': env['mac'].replace(":","-"),
                    'next-server': env['server_ip']
                })
                # start ipxe emulated netboot
                execute_line(env, "chain /start.ipxe")
        # if 'qemu-cmd' was specified in env, this means
        # all went well and we can start qemu
        # note: we just left the with context because we no
        # longer need the temporary network setup that was
        # possibly established.
        if 'qemu-cmd' in env:
            cmd = env["qemu-cmd"]
            print(cmd)
            subprocess.call(cmd, shell=True)
            if 'reboot-command' in env:
                subprocess.call(env['reboot-command'], shell=True)
