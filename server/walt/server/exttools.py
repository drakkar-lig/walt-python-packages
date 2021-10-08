from __future__ import annotations

import shutil
from subprocess import run, PIPE, Popen
import sys


class ExtTool:
    @classmethod
    def get_executable(cls, cmdname: str, required=True) -> ExtTool | None:
        """Factory function for an external executable.

        This factory checks if the given executable is available, preload the
        executable path, and raise / return None if it is not available.

        :param cmdname: Command name of full path.
        :param required: If command is not available, either return
        None (required=False) or raise FileNotFoundError (required=True)
        :raise FileNotFoundError
        """
        cmd_fullpath = shutil.which(cmdname)
        if cmd_fullpath is None:
            if required:
                raise
            else:
                return None
        return ExtTool(cmd_fullpath)

    def __init__(self, *path):
        self.path = path

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


class StreamExtTool:
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
                try:
                    line = stream.readline()
                    if line == '':
                        return
                    yield converter(line.strip())
                except GeneratorExit:
                    stream.close()
                    popen.terminate()
                    popen.wait()
                    raise
        return read_stream()


buildah = ExtTool.get_executable('buildah')
podman = ExtTool.get_executable('podman')
skopeo = ExtTool.get_executable('skopeo')
mount = ExtTool.get_executable('mount')
umount = ExtTool.get_executable('umount')
findmnt = ExtTool.get_executable('findmnt')
docker = ExtTool.get_executable('docker', required=False)
