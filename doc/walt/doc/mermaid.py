import re

# Mermaid diagrams (```mermaid code blocks) are rendered as Unicode art in the
# terminal using the termaid module. This module is optional: if it is missing
# or fails to render a diagram, the caller gets None and should fall back to
# something else.

RE_HTML_LINEBREAK = re.compile(r"<br\s*/?>")
# participant X as "Some label"  ->  participant X as Some label
RE_QUOTED_PARTICIPANT = re.compile(
    r'^(\s*(?:participant|actor)\s+\S+\s+as\s+)"(.*)"\s*$', re.MULTILINE
)
# subgraph X["Some title"]  ->  subgraph Some title
RE_QUOTED_SUBGRAPH = re.compile(r'^(\s*subgraph\s+)\S+\["(.*)"\]\s*$', re.MULTILINE)


def preprocess(source):
    # termaid does not interpret html line breaks, and it does not
    # handle the quoted labels of participants and subgraphs.
    source = RE_HTML_LINEBREAK.sub(" ", source)
    source = RE_QUOTED_PARTICIPANT.sub(r"\1\2", source)
    source = RE_QUOTED_SUBGRAPH.sub(r"\1\2", source)
    return source


# termaid layouts, from the most readable to the most compact
LAYOUTS = (
    dict(padding_x=2, padding_y=1, gap=3),
    dict(padding_x=1, padding_y=0, gap=2),
)


def render(source, max_width=None):
    """Return the diagram as a list of text lines, or None if it cannot be
    rendered (termaid not installed, unsupported syntax, ...).
    If max_width is specified, the most readable layout fitting this width is
    used, or the most compact one if none fits."""
    try:
        import termaid

        source = preprocess(source)
        for layout in LAYOUTS:
            lines = _to_lines(termaid.render(source, **layout))
            if max_width is None or max(len(line) for line in lines) <= max_width:
                break
    except Exception:
        return None
    return lines


def _to_lines(art):
    lines = [line.rstrip() for line in art.split("\n")]
    # remove empty lines at the start and end, and common left indentation
    while lines and lines[0] == "":
        lines.pop(0)
    while lines and lines[-1] == "":
        lines.pop()
    if not lines:
        raise ValueError("empty diagram")
    indent = min(len(line) - len(line.lstrip(" ")) for line in lines if line)
    return [line[indent:] for line in lines]
