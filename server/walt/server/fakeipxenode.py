#!/usr/bin/env python
import sys, subprocess, tempfile, shutil, shlex, time, random

MANUFACTURER="QEMU"
PRODUCT="Standard PC (i440FX + PIIX, 1996)"
TFTP_ROOT="/var/lib/walt/nodes/%(mac)s/tftp"

if len(sys.argv) != 5:
    print('Usage: %(prog)s <node_mac> <node_ip> <node_name> <server_ip>' % \
                dict(prog = sys.argv[0]))
    sys.exit()

mac=sys.argv[1]
ip=sys.argv[2]
name=sys.argv[3]
server_ip=sys.argv[4]

env = {
    "mac": mac,
    "ip": ip,
    "name": name,
    "mac:hexhyp": mac.replace(":","-"),
    "manufacturer": MANUFACTURER,
    "product": PRODUCT,
    "next-server": server_ip,
    "kvm-args": "kvm -m 512 -name %(name)s \
                    -smp 4 \
                    -display none \
                    -net nic,macaddr=%(mac)s \
                    -net bridge,br=walt-net \
                    -serial mon:stdio \
                    -no-reboot"
}

def execute_line(line):
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
        return execute_line(and_conditions[0]) and execute_line(and_conditions[1])
    if cond == "or":
        return execute_line(or_conditions[0]) or execute_line(or_conditions[1])
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
        # we have to release the file after reading it
        try:
            with open(TFTP_ROOT % env + path) as f:
                lines = f.readlines()
        except Exception:
            return False
        for line in lines:
            if not execute_line(line):
                return False
        return True
    # handle "imgfree" directive
    if words[0] == 'imgfree':
        return True     # nothing to do here
    # handle "initrd" directive
    if words[0] == 'initrd':
        initrd_path = ' '.join(words[1:])
        initrd_path = TFTP_ROOT % env + initrd_path
        initrd_copy = TMPDIR + '/initrd'
        try:
            shutil.copyfile(initrd_path, initrd_copy)
        except Exception:
            return False
        env["kvm-args"] += " -initrd " + initrd_copy
        return True
    # handle "boot" directive
    if words[0] == 'boot':
        kernel_path = words[1]
        kernel_cmdline = " ".join(words[2:])
        kernel_path = TFTP_ROOT % env + kernel_path
        kernel_copy = TMPDIR + '/kernel'
        try:
            shutil.copyfile(kernel_path, kernel_copy)
        except Exception:
            return False
        env["kvm-args"] += " -kernel " + kernel_copy
        env["kvm-args"] += " -append '" + kernel_cmdline + "'" 
        cmd = env["kvm-args"] % env
        print cmd
        subprocess.call(cmd, shell=True)
        return False    # reboot when it exits
    # handle "reboot" directive
    if words[0] == 'reboot':
        return False
    # unknown directive!
    raise NotImplementedError('Unknown directive "' + words[0] + '". Aborted.')

random.seed()
TMPDIR = tempfile.mkdtemp()
try:
    while True:
        # wait randomly to mitigate simultaneous load of various
        # virtual nodes
        time.sleep(random.random()*10)
        # start
        print("Starting...")
        execute_line("chain /start.ipxe")
except NotImplementedError as e:
    print(str(e))
shutil.rmtree(TMPDIR)
