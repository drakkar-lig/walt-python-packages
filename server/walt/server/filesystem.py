from subprocess import check_output

class Filesystem(object):
    def __init__(self, cmd_pattern):
        self.cmd_pattern = cmd_pattern
    def wrap_cmd(self, cmd):
        cmd_args = cmd.split()
        return self.cmd_pattern % dict(
            prog = cmd_args[0],
            prog_args = ' '.join(cmd_args[1:])
        ) + ' 2>/dev/null || true'
    def run_cmd(self, cmd):
        return check_output(self.wrap_cmd(cmd), shell=True)
    def ping(self):
        return self.run_cmd('echo ok').strip() == 'ok'
    def get_file_type(self, path):
        # the output of stat may depend on locale settings.
        # we compare with what is obtained using a regular file ('/etc/hostname')
        # and a directory ('/').
        stat_cmd = 'stat -tc %%F /etc/hostname / %s' % path
        lines = self.run_cmd(stat_cmd).splitlines()
        if len(lines) < 3:
            return None
        if lines[0] == lines[2]:
            return 'f'
        elif lines[1] == lines[2]:
            return 'd'
        else:
            return 'o'  # other
