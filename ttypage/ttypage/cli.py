"""ttypage: view a markdown file in the terminal.

Relative links to other markdown files can be followed (<tab>/<shift-tab>
to select a link, <enter> to open it, <backspace> to come back).
"""
import argparse
import sys
from importlib.util import find_spec
from pathlib import Path
from urllib.parse import unquote, urlsplit

from ttypage.pager import Page, Pager

MARKDOWN_SUFFIXES = (".md", ".markdown")


def read_markdown(path):
    """Return (content, error_message)."""
    try:
        return path.read_text(), None
    except (OSError, UnicodeDecodeError) as e:
        reason = getattr(e, "strerror", None) or str(e)
        return None, f"Cannot read {path}: {reason}"


class FilePager(Pager):
    """Pager for markdown files (location = file path)."""

    def get_page(self, path, rows, cols):
        content, error = read_markdown(path)
        if content is None:
            content = f"*{error}*"
        return Page(markdown=content, scroll=0)

    def resolve_link(self, destination):
        url = urlsplit(destination)
        if url.scheme != "" or url.netloc != "":
            return None  # e.g., https://..., mailto:...
        link_path = unquote(url.path)
        if not link_path.endswith(MARKDOWN_SUFFIXES):
            return None
        # relative links are relative to the directory of the current file
        return (self.location.parent / link_path).resolve()


def run(args=None):
    parser = argparse.ArgumentParser(
        prog="ttypage",
        description="View a markdown file in the terminal.",
        epilog="Keys: <up>/<down>, <page-up>/<page-down>: scroll; "
               "<tab>/<shift-tab>, <enter>/<backspace>: follow links "
               "to other markdown files; <q>: quit.",
    )
    parser.add_argument("file", help="markdown file to display")
    args = parser.parse_args(args)
    if find_spec("commonmark") is None:
        print("ttypage: displaying markdown requires the markdown extra:\n"
              "  pip install 'ttypage[markdown]'", file=sys.stderr)
        sys.exit(1)
    path = Path(args.file).resolve()
    content, error = read_markdown(path)
    if content is None:
        print(f"ttypage: {error}", file=sys.stderr)
        sys.exit(1)
    if sys.stdout.isatty() and sys.stdin.isatty():
        FilePager().run(path)
    else:
        # not interactive (e.g., output piped to another command)
        sys.stdout.write(content)

