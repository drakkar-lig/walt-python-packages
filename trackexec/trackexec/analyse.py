import numpy as np
import sys

from trackexec.formatting import columnate, format_paragraph
from trackexec.const import SEC_AS_TS
from trackexec.reader import LogsReader


SORT_FIELDS = {
    "cumulated-runtime": "cum_duration",
    "average-runtime": "avg_duration",
    "frequency": "num_occurences",
}

DTYPE = np.dtype([
            ("file_id", np.uint16),
            ("lineno", np.uint16),
            ("num_occurences", np.uint32),
            ("cum_duration", np.float64),
            ("avg_duration", np.float64)])


def location_info(reader, row):
    location = reader.short_file_location(row.file_id, row.lineno, 40)
    source_line = reader.read_source_file(row.file_id).splitlines()[row.lineno-1]
    source_line = source_line.strip()
    if len(source_line) > 40:
        source_line = source_line[:36] + "..."
    return location, source_line


def trackexec_analyse(trackexec_log_dir, num_items, file_id, sort_field):
    # retrieve src_index info as an array
    reader = LogsReader(trackexec_log_dir)
    it = ((tuple(k) + tuple(v[1:]) + (0.,)) for k, v in reader.src_index.items())
    a = np.fromiter(it, DTYPE).view(np.recarray)
    # restrict to a given file_id if specified
    if file_id is not None:
        a = a[a.file_id == file_id]
        if len(a) == 0:
            print("Sorry file id not found in execution trace.")
            sys.exit(1)
    # convert cum_duration to seconds
    a.cum_duration /= SEC_AS_TS
    # compute avg_duration
    a.avg_duration = (a.cum_duration / a.num_occurences)
    if file_id is None:
        # sort by avg code execution time
        # and display with source info
        arr_sort_idx = a[sort_field].argsort()[-num_items:][::-1]
        rows = []
        headers = ["File ID", "Source code location", "Source code",
                   "Cumulated runtime", "Average runtime",
                   "Code path frequency"]
        for row in a[arr_sort_idx]:
            location, source_line = location_info(reader, row)
            rows.append((row.file_id, location, source_line,
                f"{row.cum_duration:.3f}s", f"{row.avg_duration:.3f}s",
                f"seen {row.num_occurences} times"))
        print(format_paragraph(
            "Hottest source points regarding execution time (estimated):",
            columnate(rows, headers, align="<<<>>>")))
    else:
        info_per_line = {}
        for row in a:
            info_per_line[row.lineno] = row
        file_source_lines = reader.read_source_file(file_id).splitlines()
        unseen_linenos = []
        for lineno in range(1, len(file_source_lines)+1):
            if lineno not in info_per_line:
                unseen_linenos += [lineno]
        it = ((file_id, lineno, 0, 0, 0) for lineno in unseen_linenos)
        a_unseen = np.fromiter(it, DTYPE)
        a_new = np.empty(len(a) + len(a_unseen), DTYPE)
        a_new[:len(a)] = a
        a_new[len(a):] = a_unseen
        a = a_new.view(np.recarray)
        arr_sort_idx = a.lineno.argsort()
        rows = []
        headers = ["", "Cumulated runtime", "Average runtime",
                   "Code path frequency", "Source code"]
        for row in a[arr_sort_idx]:
            source_line = file_source_lines[row.lineno-1]
            if row.num_occurences == 0:
                rows.append((row.lineno, "", "", "", source_line))
            else:
                rows.append((row.lineno,
                    f"{row.cum_duration:.3f}s", f"{row.avg_duration:.3f}s",
                    f"seen {row.num_occurences} times", source_line))
        print(columnate(rows, headers, align=">>>><"))


def run():
    """Entry point of `trackexec analyse` as a standalone command."""
    from trackexec.cli import run_subcommand
    run_subcommand("analyse")
