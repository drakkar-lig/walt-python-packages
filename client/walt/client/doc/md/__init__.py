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

def display_topic_list():
    file_list = sorted(resource_listdir(__name__, '.'))
    print('The following help topics are available:')
    print((', '.join(filename[:-3] for filename in file_list \
            if filename.endswith('.md'))))
