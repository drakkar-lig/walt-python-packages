import numpy as np
import sys

from pathlib import Path
from plumbum import cli
from walt.common.formatting import columnate, format_paragraph
from walt.server.trackexec.const import SEC_AS_TS
from walt.server.trackexec.reader import LogsReader


def location_info(reader, row):
    location = reader.short_file_location(row.file_id, row.lineno, 40)
    source_line = reader.read_source_file(row.file_id).splitlines()[row.lineno-1]
    source_line = source_line.strip()
    if len(source_line) > 40:
        source_line = source_line[:36] + "..."
    return location, source_line


def trackexec_analyse(trackexec_log_dir, num_items):
    # retrieve src_index info as an array
    reader = LogsReader(trackexec_log_dir)
    it = ((tuple(k) + tuple(v[1:]) + (0.,)) for k, v in reader.src_index.items())
    a = np.fromiter(it, np.dtype([
            ("file_id", np.uint16),
            ("lineno", np.uint16),
            ("num_occurences", np.uint32),
            ("cum_duration", np.float64),
            ("avg_duration", np.float64),
    ])).view(np.recarray)
    # convert cum_duration to seconds
    a.cum_duration /= SEC_AS_TS
    # compute avg_duration
    a.avg_duration = (a.cum_duration / a.num_occurences)
    # sort by avg code execution time
    # and display with source info
    arr_avg_hot_idx = a.avg_duration.argsort()[-num_items:][::-1]
    rows = []
    headers = ["Source code location", "Source code",
               "Cumulated runtime", "Average runtime",
               "Code path frequency"]
    for row in a[arr_avg_hot_idx]:
        location, source_line = location_info(reader, row)
        rows.append((location, source_line,
            f"{row.cum_duration:.3f}s", f"{row.avg_duration:.3f}s",
            f"seen {row.num_occurences} times"))
    print(format_paragraph(
        "Hottest source points regarding execution time (estimated):",
        columnate(rows, headers, align="<<>>>")))


def _usage_error(tip):
    print(tip)
    sys.exit(1)


def TrackExecLogDir(s):
    p = Path(s)
    if not p.exists():
        _usage_error(f"No such directory: {s}")
    if not p.is_dir():
        _usage_error(f"Not a directory: {s}")
    if not (p / "log_index").exists():
        _usage_error('The specified directory must contain a "log_index" file.')
    return p


class TrackExecAnalyseCli(cli.Application):

    num_items = cli.SwitchAttr(
        "--num-items",
        int,
        default=20,
        help="""how many of the most time-consuming hotpoints should be displayed""",
    )

    def main(self, trackexec_log_dir : TrackExecLogDir):
        """Analyse WalT server process execution logs"""
        trackexec_analyse(trackexec_log_dir, self.num_items)
        sys.exit(1)


def run():
    TrackExecAnalyseCli.run()
