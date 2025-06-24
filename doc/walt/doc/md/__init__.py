import re
import sys

from importlib.resources import files
from walt.doc.pager import DocPager


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


def display_doc(topic):
    if sys.stdout.isatty() and sys.stdin.isatty():
        pager = DocPager(get_md_content)
        pager.display_topic(topic)
    else:
        content = get_md_content(topic, err_out=True)
        if content is not None:
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
