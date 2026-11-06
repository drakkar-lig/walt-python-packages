import re
import socket
import sys

from importlib.resources import files
from walt.doc.pager import Page, Pager


def get_md_content(topic, err_out=False):
    try:
        import walt.doc.md
        path = files(walt.doc.md) / (topic + ".md")
        return path.read_text()
    except Exception:
        if err_out:
            print('Sorry, no such help topic. (tip: use "walt help list")',
                  file=sys.stderr)
        return


class DocPager(Pager):
    """Pager for WalT help topics (location = topic name)."""

    def get_page(self, topic, rows, cols):
        content = get_md_content(topic)
        if content is None:
            content = f"Sorry, no such help topic: {topic}."
        return Page(markdown=content, scroll=0)

    def resolve_link(self, destination):
        if destination.endswith(".md"):
            return destination[:-3]
        return None

    def format_url(self, url):
        # prefix relative URLs with "http://<hostname>"
        if not url.startswith("http"):
            url = f"http://{socket.gethostname()}/{url.lstrip('/')}"
        return url

    def diagram_fallback_message(self, topic):
        # URL of the topic in the web documentation served by the server
        # (or of the documentation index if the topic is not known).
        url = f"http://{socket.gethostname()}/doc/"
        if topic is not None:
            # note: the help-intro topic is the index page (see sphinx/conf.py)
            page = "index" if topic == "help-intro" else topic
            url += f"{page}.html"
        return ("This diagram cannot be displayed in the terminal. "
                f"Please see the web documentation: {url}")


def display_doc(topic):
    content = get_md_content(topic, err_out=True)
    if content is None:
        return
    if sys.stdout.isatty() and sys.stdin.isatty():
        DocPager().run(topic)
    else:
        print(content)


def get_topics():
    import walt.doc.md
    file_iter = files(walt.doc.md).iterdir()
    return (f.name[:-3] for f in file_iter if f.name.endswith(".md"))


def iter_topic_header():
    for topic in get_topics():
        md_content = get_md_content(topic)
        header = ""
        for line in re.split("[\n#]+", md_content):
            line = line.strip()
            if len(line) > 0:
                header = line
                break
        yield (topic, header)


def get_described_topics():
    topic_dict = {topic: header for topic, header in iter_topic_header()}
    max_topic_len = max(len(topic) for topic in topic_dict.keys())
    for topic, header in topic_dict.items():
        yield f"{topic:<{max_topic_len}} -- {header}"


def display_topic_list():
    print("The following help topics are available:")
    for described_topic in sorted(get_described_topics()):
        print(described_topic)
