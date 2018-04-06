import json, re, binascii, os
from os.path import expanduser
from collections import OrderedDict
from walt.common.tools import read_json
from getpass import getpass

CONFIG_FILE_TOP_COMMENT="""\
WalT configuration file
***********************
This file was automatically generated.
You are allowed to edit the configuration values if needed.
However, instead of changing a value, you should consider removing the
related line instead. This would cause the walt client to prompt for this value
again, your new entry would pass an appropriate validity check, and this file
would be generated again accordingly.
"""

# This is not secure at all, we will just make passwords unreadable for someone spying
# your screen. The security is actually based on the access rights of the conf file
# (it is readable by the owner only).
# The docker framework relies on the same policy regarding password storage in
# .docker/conf.json or .dockercfg.
KEY="RAND0M STRING T0 HIDE A PASSW0RD"
def xor(password):
    key = (len(password) / len(KEY) +1)*KEY     # repeat if KEY is too short
    return "".join(chr(ord(a)^ord(b)) for a,b in zip(key,password))

def ask_config_item(key, coded=False):
    msg = '%s: ' % key
    while True:
        if coded:
            value = getpass(msg)
        else:
            value = raw_input(msg)
        if value.strip() == '':
            continue
        break
    return value

def encode(value):
    return binascii.hexlify(xor(value))

def decode(coded_value):
    return xor(binascii.unhexlify(coded_value))

def get_config_file():
    return expanduser('~/.waltrc')

def get_config_from_file(coded_items):
    config_file = get_config_file()
    modified = False
    conf = read_json(config_file)
    if conf == None:
        if os.path.exists(config_file):
            print "Warning: %s file exists, but it could not be parsed properly." \
                            % config_file
        conf = OrderedDict()
    for key in conf:
        if key in coded_items:
            conf[key] = decode(conf[key])
    return conf

class ConfigFileSaver(object):
    def __init__(self):
        self.item_groups = []
    def __enter__(self):
        return self
    def __exit__(self, type, value, tb):
        # concatenate all and write the file
        config_file = get_config_file()
        with open(config_file, 'w') as f:
            f.write(self.printed())
        os.chmod(config_file, 0o600)
        print '\nConfiguration was stored in %s.\n' % config_file
    def add_item_group(self, desc, explain=None):
        self.item_groups.append(dict(
            desc    = desc,
            explain = explain,
            items   = []
        ))
    def add_item(self, key, value, coded=False):
        comment = None
        if coded:
            comment = '(%s value is encoded.)' % key
            value   = encode(value)
        self.item_groups[-1]['items'].append(dict(
            key     = key,
            value   = value,
            comment = comment
        ))
    def comment_section(self, lines, section, indent=0):
        return lines.extend([ (' ' * indent) + '# ' + line \
                            for line in section.splitlines() ])
    def printed(self):
        lines = [ '' ]
        self.comment_section(lines, CONFIG_FILE_TOP_COMMENT)
        lines.extend(['', '{'])
        last_item_line = None
        for item_group in self.item_groups:
            desc = item_group['desc']
            explain = item_group['explain']
            # add group-level 'json comments'
            lines.append('')
            self.comment_section(
                    lines,
                    '%s\n%s' % (desc, re.sub('.', '-', desc)),
                    indent = 4)
            if explain:
                self.comment_section(
                    lines, explain, indent = 4)
            # add items
            for item in item_group['items']:
                key     = item['key']
                value   = item['value']
                comment = item['comment']
                if comment:
                    self.comment_section(lines, comment, indent = 4)
                # get json output for this item only
                # (by creating a temporary dictionary with just this item)
                item_and_value = json.dumps({key:value}, indent=4).splitlines()[1:-1]
                item_and_value[-1] += ','
                lines.extend(item_and_value)
                last_item_line = len(lines) -1
        # remove the comma after the last item
        lines[last_item_line] = lines[last_item_line][:-1]
        lines.append('}')
        return '\n'.join(lines) + '\n'

def set_conf(in_conf):
    global conf_dict
    conf_dict = in_conf

class Conf(object):
    def __getitem__(self, key):
        return conf_dict[key]

conf_dict = None
conf = Conf()

