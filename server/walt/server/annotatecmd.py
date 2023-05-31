import pickle
import sys

from walt.common.tools import do

USAGE = """\
Usage:  $ walt-annotate-cmd [--mode [line|pickle4]] <cmd> <arg>...
"""


class StreamAnnotation:
    def __init__(self, dump, out_stream, tag):
        self.dump = dump
        self.out_stream = out_stream
        self.tag = tag

    def write(self, s):
        self.dump(self.out_stream, self.tag, s)


def run():
    mode = "line"
    argv = sys.argv[1:]
    bad_usage = False
    while len(argv) > 0:
        arg = argv[0]
        if arg == "--mode":
            if len(argv) < 2:
                bad_usage = True
                break
            mode, argv = argv[1], argv[2:]
        else:
            # end of options
            break
    if len(argv) < 1:
        bad_usage = True
    if mode not in ("line", "pickle4"):
        print('Error: mode should be "line" or "pickle4".')
        bad_usage = True
    if bad_usage:
        print(USAGE)
        sys.exit(2)
    if mode == "line":

        def dump(out_stream, tag, obj):
            out_stream.write(f"{tag}: {repr(obj)}\n")
            out_stream.flush()

    elif mode == "pickle4":

        def dump(out_stream, tag, obj):
            pickle.dump((tag, obj), out_stream.buffer, protocol=4)
            out_stream.flush()

    else:
        raise NotImplementedError

    retcode = do(
        argv,
        text=False,
        stdout=StreamAnnotation(dump, sys.stdout, "stdout"),
        stderr=StreamAnnotation(dump, sys.stderr, "stderr"),
    )
    dump(sys.stdout, "retcode", retcode)


if __name__ == "__main__":
    run()
