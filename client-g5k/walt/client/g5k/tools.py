import json
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime

KAVLAN_FAILURE_DELAY = 3


def get_local_g5k_site():
    return socket.gethostname()[1:]


PYTHON_WRAPPER = """\
import subprocess
run_args = %(run_args)s
run_kwargs = %(run_kwargs)s
subprocess.run(*run_args, **run_kwargs)
"""


class Cmd:
    def __init__(self, site, cmd_args, input=None):
        self._popen_kwargs = dict(encoding=sys.stdout.encoding)
        self._input = input
        if site == get_local_g5k_site():
            self._popen_args = (list(cmd_args),)
        else:
            # In order to pass the command line arguments correctly to the
            # remote site without complex escaping, we pass a simple python
            # script including these arguments to stdin of ssh.
            # This script will be passed to the remote python3 command
            # which will execute it.
            run_args = (list(cmd_args),)
            run_kwargs = {}
            # if input is specified, pass it to the python_wrapper_code too
            if self._input is not None:
                run_kwargs.update(input=self._input, encoding=sys.stdout.encoding)
            python_wrapper_code = PYTHON_WRAPPER % dict(
                run_args=repr(run_args), run_kwargs=repr(run_kwargs)
            )
            self._input = python_wrapper_code
            self._popen_args = (["ssh", site, "python3", "-u", "-"],)

    def run_and_follow(self):
        popen = subprocess.Popen(
            *self._popen_args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            **self._popen_kwargs,
        )
        if self._input is not None:
            popen.stdin.write(self._input)
            popen.stdin.flush()
            popen.stdin.close()
        yield None  # notify startup is OK
        while True:
            try:
                line = popen.stdout.readline()
                if line == "":
                    break  # empty read
                yield line.strip()
            except GeneratorExit:
                while True:
                    try:
                        retcode = popen.wait(timeout=1)
                        if retcode != 0:
                            raise Exception(
                                f'Command returned exit code {retcode}')
                        break
                    except subprocess.TimeoutExpired:
                        popen.terminate()
                popen.stdout.close()
                raise

    @contextmanager
    def monitor(self):
        try:
            monitoring = self.run_and_follow()
            next(monitoring)
            yield monitoring
        finally:
            monitoring.close()

    def run(self):
        return subprocess.run(
            *self._popen_args,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            input=self._input,
            **self._popen_kwargs,
        )


def run_cmd_on_site(
    info,
    site,
    cmd_args,
    add_job_id_option=False,
    err_out=True,
    background=False,
    **run_kwargs,
):
    if add_job_id_option:
        site_job_id = info["sites"][site]["job_id"]
        cmd_args[1:1] = ["-j", str(site_job_id)]
    cmd = Cmd(site, cmd_args, **run_kwargs)
    try:
        if background:
            monitoring = cmd.run_and_follow()
            next(monitoring)  # wait for command startup
            return monitoring
        else:
            info = cmd.run()
            return info.stdout
    except subprocess.CalledProcessError as e:
        if err_out:
            print(e, file=sys.stderr)
            print(e.stdout, file=sys.stderr)
            raise
        else:
            return e


def oarstat(info, site):
    job_id = info["sites"][site].get("job_id")
    if job_id is None:
        print("oarstat(): no job_id found for site {site}.", file=sys.stderr)
        return None
    try:
        out = run_cmd_on_site(info, site, f"oarstat -j {job_id} -f -J".split())
        return json.loads(out)[job_id]
    except subprocess.CalledProcessError:
        return None  # error already printed on stderr by run_cmd_on_site()


def set_vlan(info, site, vlan_id, *nodes):
    remaining_nodes = nodes
    retries = 3
    while True:
        num_nodes = len(remaining_nodes)
        nodes_spec = " ".join(("-m " + node) for node in remaining_nodes)
        run_cmd_on_site(
            info, site, f"kavlan -s -i {vlan_id} {nodes_spec}".split(), True
        )
        remaining_nodes = []
        verif = run_cmd_on_site(info, site, f"kavlan -g {nodes_spec}".split(), False)
        for line in verif.splitlines():
            node, vlan = line.split()
            node = node[:-1]  # "<node>:" -> "<node>"
            if str(vlan) != str(vlan_id):
                remaining_nodes.append(node)
        if len(remaining_nodes) == 0:
            return  # ok done
        # failed on some nodes
        if len(remaining_nodes) < num_nodes:
            # we are progressing, continue
            retries = 3
            time.sleep(KAVLAN_FAILURE_DELAY)
            continue
        retries -= 1
        if retries == 0:
            # stop retrying!
            break
        else:
            time.sleep(KAVLAN_FAILURE_DELAY)
            continue
    # still not progressing after 3 tries
    raise Exception(
        f"kavlan failed to attach vlan {vlan_id} on " + ", ".join(remaining_nodes)
    )


def printed_date_from_ts(ts):
    return " ".join(datetime.fromtimestamp(ts).strftime("%c").split())
