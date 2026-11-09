"""The `trackexec` command."""
import argparse
import os
import sys
from pathlib import Path

SORT_COLUMNS = ("cumulated-runtime", "average-runtime", "frequency")


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
    args = parser.parse_args(args)
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
