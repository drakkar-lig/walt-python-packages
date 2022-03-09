import re
from pkg_resources import resource_string, resource_listdir
from walt.client.doc.pager import Pager

def get_md_content(topic, err_out=False):
    try:
        return resource_string(__name__, topic + ".md").decode('utf-8')
    except:
        if err_out:
            print('Sorry, no such help topic. (tip: use "walt help list")')
        return

def display_doc(topic):
    pager = Pager(get_md_content)
    pager.display_topic(topic)

def get_topics():
    file_list = resource_listdir(__name__, '.')
    return (filename[:-3] for filename in file_list \
            if filename.endswith('.md'))

def get_described_topics():
    for topic in get_topics():
        md_content = get_md_content(topic)
        header = ''
        for line in re.split('[\n#]+', md_content):
            line = line.strip()
            if len(line) > 0:
                header = line
                break
        yield (topic, header)

def display_topic_list():
    print('The following help topics are available:')
    topic_dict = { topic: header for topic, header in get_described_topics() }
    max_topic_len = max(len(topic) for topic in topic_dict.keys())
    for topic, header in sorted(topic_dict.items()):
        print(f"{topic:<{max_topic_len}} -- {header}")
