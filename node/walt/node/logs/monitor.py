#!/usr/bin/env python
import os, time, select
from walt.common.tools import fd_copy, set_non_blocking
from walt.common.tty import set_tty_size,     \
                            acquire_controlling_tty, tty_disable_echoctl
from walt.node.logs.flow import LogsFlowToServer

# See comments in node/sh/walt-monitor.
# This file implements the server side part of walt-monitor.

BUFFER_SIZE = 1024

def read_process_env(pid, **kwargs):
    with open('/proc/%d/environ' % pid) as f:
        return dict(    statement.split('=',1) \
                for statement in f.read().strip('\0').split('\0'))

def read_process_cmdline(pid):
    with open('/proc/%d/cmdline' % pid) as f:
        return f.read().strip('\0').split('\0')

def monitor_cmd(pid, env, args, tty_slave_fd, uid, gid, tty_size, **kwargs):
    os.chdir(env['PWD'])
    os.dup2(tty_slave_fd, 0)
    os.dup2(tty_slave_fd, 1)
    os.dup2(tty_slave_fd, 2)
    set_tty_size(tty_slave_fd, tty_size)
    os.close(tty_slave_fd)
    os.setgid(gid)
    os.setuid(uid)
    # cmdline is: bash walt-monitor <cmd-args>
    os.execvpe(args[2], args[2:], env)

def parent_handler(pid, pipe_r, tty_master_fd, args, **kwargs):
    logstream = "%s.%d.monitor" % (
        os.path.basename(args[2]), pid
    )
    logs_conn = LogsFlowToServer(logstream)
    logs_conn.log(line='START', timestamp=time.time())
    tty_out = os.open('/tmp/walt-monitor-stdout-%d.fifo' % pid, os.O_WRONLY)
    tty_in = os.open('/tmp/walt-monitor-stdin-%d.fifo' % pid, os.O_RDONLY)
    fds = [pipe_r, tty_master_fd, tty_in]
    # set non blocking for efficiency
    set_non_blocking(tty_master_fd)
    logline = ''
    logline_ts = None
    while True:
        r, w, e = select.select(fds,[],[])
        ts = time.time()
        if tty_master_fd in r:
            s = fd_copy(tty_master_fd, tty_out, BUFFER_SIZE) or fds.remove(tty_master_fd)
            if s:
                logline += s
                if logline_ts == None:
                    logline_ts = ts
                while '\n' in logline:
                    complete_logline, logline = logline.split('\n', 1)
                    # send to server
                    logs_conn.log(line=complete_logline, timestamp=logline_ts)
                    if logline == '':
                        logline_ts = None
                    else:
                        logline_ts = ts
        elif tty_in in r:
            fd_copy(tty_in, tty_master_fd, 1) or fds.remove(tty_in)
        elif pipe_r in r:
            break
    logs_conn.log(line='END', timestamp=time.time())
    logs_conn.close()
    # this will stop walt-monitor
    os.close(tty_out)

def child_handler(**context):
    acquire_controlling_tty(context['tty_slave_fd'])
    env = read_process_env(**context)
    # save this new info
    context.update(env = env)
    monitor_cmd(**context)

def handle_monitor_request(*args):
    pid, uid, gid, tty_rows, tty_cols = (int(w) for w in args)
    # we create a pipe in order to detect when the child exits.
    pipe_r, pipe_w = os.pipe()
    # we create a virtual tty (master-slave pair)
    tty_master_fd, tty_slave_fd = os.openpty()
    # we disallow the tty to print "^C" when receiving ctrl-c, etc.
    # (otherwise it would be inserted in the log line)
    tty_disable_echoctl(tty_slave_fd)
    # we need to read walt-monitor process cmdline
    args = read_process_cmdline(pid)
    # save all this info
    context = dict( pid = pid,
                    uid = uid,
                    gid = gid,
                    tty_size = (tty_rows, tty_cols),
                    pipe_r = pipe_r,
                    tty_master_fd = tty_master_fd,
                    tty_slave_fd = tty_slave_fd,
                    args = args)
    # we need to fork, see below
    res = os.fork()
    if (res > 0):
        os.close(tty_slave_fd)
        os.close(pipe_w)
        # the parent will be the interface between
        # walt-monitor (through stdin and stdout fifos) and the virtual tty
        parent_handler(**context)
    else:
        os.close(tty_master_fd)
        os.close(pipe_r)
        # the child will run the command inside the virtual tty
        child_handler(**context)

