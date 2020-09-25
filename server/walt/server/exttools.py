from subprocess import run, CalledProcessError, PIPE, Popen
import sys

class ExtTool:
    def __init__(self, *path):
        self.path = tuple(path)
    @property
    def stream(self):
        return StreamExtTool(*self.path)
    def __getattr__(self, attr):
        sub_path = self.path + (attr,)
        sub_tool = ExtTool(*sub_path)
        setattr(self, attr, sub_tool)   # shortcut for next time
        return sub_tool
    def __call__(self, *args, input=None):
        return run(self.path + args,
                   check=True,
                   input=input,
                   stdout=PIPE,
                   encoding=sys.stdout.encoding).stdout.strip()

class StreamExtTool():
    def __init__(self, *path):
        self.path = tuple(path)
    def __call__(self, *args, converter = None, out_stream = 'stdout'):
        if converter is None:
            converter = lambda line: line
        # this function must remain a function and not become
        # an iterator itself.
        # this is because we have to make sure popen is executed when __call__()
        # is called, and not delayed up to the first __next__() call.
        # otherwise, calling podman.events.stream() for instance would
        # miss all events up to first next() call on the returned iterator.
        popen_stream_arg = { out_stream: PIPE }
        popen = Popen(self.path + args,
                    encoding=sys.stdout.encoding, **popen_stream_arg)
        stream = getattr(popen, out_stream)
        def read_stream():
            while True:
                line = stream.readline()
                if line == '':
                    return
                yield converter(line.strip())
        return iter(read_stream())

buildah = ExtTool('buildah')
podman = ExtTool('podman')
skopeo = ExtTool('skopeo')
mount = ExtTool('mount')
umount = ExtTool('umount')
findmnt = ExtTool('findmnt')
docker = ExtTool('docker')
