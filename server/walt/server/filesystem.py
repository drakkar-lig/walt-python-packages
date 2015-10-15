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
        if len(self.run_cmd('find %s' % path)) == 0:
            return None
        for ftype in [ 'f', 'd' ]:
            check_cmd = 'find %(path)s -type %(ftype)s -maxdepth 0 -printf %(ftype)s' % \
                dict(
                    path = path,
                    ftype = ftype
                )
            result = self.run_cmd(check_cmd)
            if len(result) > 0:
                return result
        return 'o'  # other
