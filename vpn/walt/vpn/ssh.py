import os
import shlex
import sys
from subprocess import DEVNULL, check_call


# For easy management of per-command ssh identity, we always start a new ssh-agent
# (even if there is already one agent running on the system). This agent will
# be running as long a the subcommand specified is running. Since we actually
# have several things to do (2 things, see function 'ssh_helper' below), we call
# this program (i.e. walt-vpn-ssh-helper) recursively, with first arg set to
# 'ssh-helper', and get to function 'ssh_helper' below.
def format_ssh_agent_command(key_path, ssh_command):
    return ["ssh-agent", sys.argv[0], "ssh-helper-step2", key_path] + ssh_command


def ssh_helper_step2(key_path, *ssh_command):
    # We add the key explicitely using ssh-add.
    # (Using ssh option "-o AddKeysToAgent=yes" on command ssh apparently does not
    # work: it only adds the key, not the certificate.)
    check_call(["ssh-add", key_path], stderr=DEVNULL)
    # replace this current process with the specified ssh command
    os.execvp(ssh_command[0], ssh_command)


def helper():
    # if arg is "ssh-helper", this means we were called recursively.
    if sys.argv[1] == "ssh-helper-step2":
        return ssh_helper_step2(*sys.argv[2:])

    # otherwise, this is the standard call.
    key_path = sys.argv[1]
    ssh_command = sys.argv[2:]
    ssh_agent_command = format_ssh_agent_command(key_path, ssh_command)
    os.execvp(ssh_agent_command[0], ssh_agent_command)


def ssh_with_identity(key_path, ssh_command):
    return shlex.split(
        "%(helper)s %(key_path)s %(cmd)s"
        % dict(helper="walt-vpn-ssh-helper", key_path=key_path, cmd=ssh_command)
    )
