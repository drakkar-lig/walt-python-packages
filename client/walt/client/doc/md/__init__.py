import os
import sys

from pkg_resources import resource_string, resource_listdir
from walt.client.doc.markdown import MarkdownRenderer
from walt.client.doc.pager import Pager

def display_doc(topic):
    try:
        content = resource_string(__name__, topic + ".md").decode('utf-8')
    except:
        print('Sorry, no such help topic. (tip: use "walt help list")')
        return
    if os.isatty(sys.stdout.fileno()):
        renderer = MarkdownRenderer()
        text = renderer.render(content)
        pager = Pager()
        pager.display(text)
    else:
        print(content)
        # For debugging colors with hexdump, prefer:
        #print(MarkdownRenderer().render(content))

def display_topic_list():
    file_list = sorted(resource_listdir(__name__, '.'))
    print('The following help topics are available:')
    print(', '.join(filename[:-3] for filename in file_list \
            if filename.endswith('.md')))
