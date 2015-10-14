
from subprocess import check_output

class Filesystem(object):
    def __init__(self, docker, image_fullname):
        self.docker = docker
        self.image_fullname = image_fullname
    def get_file_type(self, path):
        # the output of stat may depend on the locale settings in the image.
        # we compare with what is obtained using a regular file ('/etc/hostname')
        # and a directory ('/').
        cmd = "docker run --rm -i --entrypoint stat %s -tc %%F /etc/hostname / %s 2>/dev/null || true" % \
                (self.image_fullname, path)
        lines = check_output(cmd, shell=True).splitlines()
        if len(lines) < 3:
            return None
        if lines[0] == lines[2]:
            return 'f'
        if lines[1] == lines[2]:
            return 'd'
        return 'o'  # other
