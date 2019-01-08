#!/usr/bin/env python
import sys, subprocess, tempfile, shutil, shlex, time, random, os.path
from walt.common.apilink import ServerAPILink
from walt.common.tcp import write_pickle, client_sock_file, \
                            Requests
from walt.common.constants import WALT_SERVER_TCP_PORT

MANUFACTURER = "QEMU"
KVM_RAM = 512
KVM_CORES = 4
KVM_ARGS = "kvm -m " + str(KVM_RAM) + "\
                -name %(name)s \
                -smp " + str(KVM_CORES) + "\
                -display none \
                -net nic,macaddr=%(mac)s,model=virtio \
                -net bridge,br=walt-net \
                -serial mon:stdio \
                -no-reboot"

def get_qemu_product_name():
    line = subprocess.check_output('kvm -machine help | grep default', shell=True)
    line = line.replace('(default)', '')
    return line.split(' ', 1)[1].strip()

def get_env_start():
    if len(sys.argv) != 6:
        print('Usage: %(prog)s <node_mac> <node_ip> <node_model> <node_name> <server_ip>' % \
                    dict(prog = sys.argv[0]))
        sys.exit()
    mac, ip, model, name, server_ip = sys.argv[1:]
    return {
        "mac": mac,
        "ip": ip,
        "model": model,
        "name": name,
        "hostname": name,
        "mac:hexhyp": mac.replace(":","-"),
        "manufacturer": MANUFACTURER,
        "product": get_qemu_product_name(),
        "next-server": server_ip,
        "kvm-args": ' '.join(KVM_ARGS.split())
    }

def send_register_request(env):
    with ServerAPILink(env['next-server'], 'VSAPI') as server:
        vci = 'walt.node.' + env['model']
        return server.register_device(vci, '', env['ip'], env['mac'])

def add_network_info(env):
    with ServerAPILink(env['next-server'], 'VSAPI') as server:
        info = server.get_device_info(env['mac'])
        print(info)
        if info is None:
            return False
        env.update(netmask=info['netmask'], gateway=info['gateway'])

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
    status = f.readline().strip()
    if status == 'OK':
        # read size
        size = int(f.readline().strip())
        # receive content
        content = f.read(size)
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
        print ' '.join(words[1:])
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
        for line in content.splitlines():
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
        env["kvm-args"] += " -initrd " + initrd_copy
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
            env["kvm-args"] += " -kernel " + kernel_copy
            env["kvm-args"] += " -append '" + kernel_cmdline + "'"
        if words[0] == 'boot':
            cmd = env["kvm-args"] % env
            print cmd
            subprocess.call(cmd, shell=True)
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

def random_wait():
    delay = int(random.random()*10) + 1
    while delay > 0:
        print 'waiting for %ds' % delay
        time.sleep(1)
        delay -= 1

def run():
    random.seed()
    TMPDIR = tempfile.mkdtemp()
    try:
        while True:
            # wait randomly to mitigate simultaneous load of various
            # virtual nodes
            random_wait()
            print("Starting...")
            env = get_env_start()
            env['TMPDIR'] = TMPDIR
            env['REMOTEDIRSTACK'] = ['/']
            send_register_request(env)
            add_network_info(env)
            execute_line(env, "chain /start.ipxe")
    except NotImplementedError as e:
        print(str(e))
        time.sleep(120)
    shutil.rmtree(TMPDIR)

if __name__ == "__main__":
    run()
