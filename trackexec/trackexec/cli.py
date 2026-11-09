"""The `trackexec` command."""
import argparse
import os
import sys
from pathlib import Path

SORT_COLUMNS = ("cumulated-runtime", "average-runtime", "max-runtime",
                "frequency")


def trace_dir(s):
    p = Path(s)
    if not p.exists():
        raise argparse.ArgumentTypeError(f"No such directory: {s}")
    if not p.is_dir():
        raise argparse.ArgumentTypeError(f"Not a directory: {s}")
    if not (p / "log_index").exists():
        raise argparse.ArgumentTypeError(
            f"{s}: not an execution trace (missing \"log_index\" file).")
    return p


def _add_record_args(parser):
    parser.add_argument("-o", "--output", metavar="TRACE_DIR",
                        help="directory where the execution trace should be "
                             "saved (default: trackexec-<YYMMDD-HHMMSS>)")
    parser.add_argument("-i", "--include", action="append", default=[],
                        metavar="PATH_OR_MODULE",
                        help="record the code of this file, directory or "
                             "module (may be repeated; default: the "
                             "directory of SCRIPT, or the top-level package "
                             "of MODULE)")
    parser.add_argument("-m", dest="module", metavar="MODULE",
                        help="run library module MODULE as a script "
                             "(like python -m)")
    parser.add_argument("script", nargs="?", metavar="SCRIPT",
                        help="python script to run")
    parser.add_argument("script_args", nargs="*", metavar="ARG",
                        help="arguments of SCRIPT or MODULE")


# options of the record subcommand which take a value
RECORD_VALUE_OPTIONS = ("-o", "--output", "-i", "--include")


def _split_record_argv(argv):
    """Split argv into the options of `trackexec record` and the
    arguments of the program to run, which should not be
    interpreted by argparse even if they look like options."""
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "-m":
            return argv[:i+2], argv[i+2:]
        if arg in RECORD_VALUE_OPTIONS:
            i += 2
        elif arg == "--":
            return argv[:i+2], argv[i+2:]
        elif arg.startswith("-"):
            i += 1
        else:
            return argv[:i+1], argv[i+1:]
    return argv, []


def _record_output_dir(parser, args):
    if args.output is None:
        from time import strftime
        return Path(strftime("trackexec-%y%m%d-%H%M%S"))
    output = Path(args.output)
    if output.exists():
        if not output.is_dir():
            parser.error(f"{output} exists and is not a directory.")
        if any(output.iterdir()):
            parser.error(f"Directory {output} is not empty.")
    return output


def _record(parser, args):
    import runpy
    from importlib.util import find_spec
    import trackexec
    if (args.module is None) == (args.script is None):
        parser.error("Specify either SCRIPT or -m MODULE.")
    output = _record_output_dir(parser, args)
    module_level = []
    if args.module is not None:
        # like python -m, look for modules in the current directory first
        sys.path[0] = os.getcwd()
        try:
            spec = find_spec(args.module)
        except (ImportError, ValueError):
            spec = None
        if spec is not None and spec.submodule_search_locations is not None:
            # package: python -m runs its __main__ submodule
            spec = find_spec(args.module + ".__main__")
        if spec is None:
            parser.error(f"No module named {args.module}.")
        if spec.origin is not None:
            module_level.append(spec.origin)
        default_include = args.module.split(".")[0]
        sys.argv = [args.module] + args.script_args
    else:
        script = os.path.abspath(args.script)
        if not os.path.isfile(script):
            parser.error(f"No such file: {args.script}")
        module_level.append(script)
        default_include = os.path.dirname(script)
        sys.path[0] = default_include
        sys.argv = [args.script] + args.script_args
    include = args.include or [default_include]
    try:
        trackexec.start(output, include, module_level=module_level)
    except ValueError as e:
        parser.error(str(e))
    exit_code = 0
    try:
        if args.module is not None:
            runpy.run_module(args.module, run_name="__main__", alter_sys=True)
        else:
            runpy.run_path(script, run_name="__main__")
    except SystemExit as e:
        exit_code = e.code
    except BaseException as e:
        _print_program_exception(e)
        exit_code = 130 if isinstance(e, KeyboardInterrupt) else 1
    finally:
        trackexec.stop()
        sys.stdout.flush()
        print(f"trackexec: execution trace saved in {output}\n"
              f"trackexec: replay it with: trackexec replay {output}",
              file=sys.stderr)
    sys.exit(exit_code)


def _print_program_exception(e):
    """Print the traceback of an exception raised by the recorded program,
    without the frames of trackexec and runpy, as python would do."""
    import traceback
    tb = e.__traceback__
    while tb is not None and (
            tb.tb_frame.f_code.co_filename == __file__ or
            "runpy" in tb.tb_frame.f_code.co_filename):
        tb = tb.tb_next
    traceback.print_exception(type(e), e, tb)


def _add_replay_args(parser):
    parser.add_argument("trace_dir", type=trace_dir, metavar="TRACE_DIR",
                        help="directory of the execution trace")


def _add_analyse_args(parser):
    parser.add_argument("trace_dir", type=trace_dir, metavar="TRACE_DIR",
                        help="directory of the execution trace")
    parser.add_argument("--num-items", type=int, metavar="NUM_ITEMS",
                        help="how many of the most time-consuming hot points "
                             "should be displayed (default: 20)")
    parser.add_argument("--sort-column", choices=SORT_COLUMNS,
                        type=str.lower, metavar="COLUMN",
                        help="sort by the specified column: "
                             f"{', '.join(SORT_COLUMNS)} "
                             "(default: cumulated-runtime)")
    parser.add_argument("--file-id", type=int, metavar="FILE_ID",
                        help="analyse a specific file (incompatible with "
                             "--num-items and --sort-column)")


def _replay(parser, args):
    from trackexec.player import TrackExecPlayer
    TrackExecPlayer.replay(args.trace_dir)


def _analyse(parser, args):
    from trackexec.analyse import SORT_FIELDS, trackexec_analyse
    if args.file_id is not None and (
            args.num_items is not None or args.sort_column is not None):
        parser.error("--file-id cannot be used with --num-items "
                     "or --sort-column.")
    num_items = 20 if args.num_items is None else args.num_items
    sort_column = args.sort_column or "cumulated-runtime"
    trackexec_analyse(args.trace_dir, num_items, args.file_id,
                      SORT_FIELDS[sort_column])


SUBCOMMANDS = {
    "record": (_add_record_args, _record,
               "run a python program and record its execution"),
    "replay": (_add_replay_args, _replay,
               "replay an execution trace, with a debugger-like interface"),
    "analyse": (_add_analyse_args, _analyse,
                "find the instructions which consumed the most time"),
}


def run(args=None):
    parser = argparse.ArgumentParser(
        prog="trackexec",
        description="Record, replay and analyse the execution of python code.",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True,
                                       metavar="SUBCOMMAND")
    for name, (add_args, func, help_text) in SUBCOMMANDS.items():
        subparser = subparsers.add_parser(name, help=help_text,
                                          description=help_text)
        add_args(subparser)
        subparser.set_defaults(func=func, subparser=subparser)
    if args is None:
        args = sys.argv[1:]
    script_args = []
    if len(args) > 0 and args[0] == "record":
        args, script_args = _split_record_argv(args[1:])
        args = ["record"] + args
    args = parser.parse_args(args)
    if args.subcommand == "record":
        args.script_args += script_args
    _call(args.func, args.subparser, args)


def _call(func, parser, args):
    from trackexec.tools import TraceFormatError
    try:
        func(parser, args)
    except TraceFormatError as e:
        print(f"{parser.prog}: {e}", file=sys.stderr)
        sys.exit(1)


def run_subcommand(name):
    """Run one subcommand as a standalone command (e.g., for the
    walt-server-trackexec-replay alias of `trackexec replay`)."""
    add_args, func, help_text = SUBCOMMANDS[name]
    parser = argparse.ArgumentParser(prog=os.path.basename(sys.argv[0]),
                                     description=help_text)
    add_args(parser)
    _call(func, parser, parser.parse_args())
