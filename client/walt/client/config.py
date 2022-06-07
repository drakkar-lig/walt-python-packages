import yaml, re, os
from os.path import expanduser
from collections import OrderedDict
from walt.common.config import load_conf
from getpass import getpass
from pathlib import Path

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

CONFIG_CODED_ITEMS=['password']
EXPLAIN_CREDEDENTIALS='''\
These credentials must match your account at hub.docker.com.
The username will also be used to identify your work on the WalT platform.'''

# This is not secure at all, we will just make passwords unreadable for someone spying
# your screen. The security is actually based on the access rights of the conf file
# (it is readable by the owner only).
# The docker framework relies on the same policy regarding password storage in
# .docker/conf.json or .dockercfg.
KEY=b"RAND0M STRING T0 HIDE A PASSW0RD"
def xor(password):
    key = (len(password) // len(KEY) +1)*KEY     # repeat if KEY is too short
    return bytes(a^b for a,b in zip(key,password))

def ask_config_item(key, coded=False):
    msg = '%s: ' % key
    while True:
        if coded:
            value = getpass(msg)
        else:
            value = input(msg)
        if value.strip() == '':
            continue
        break
    return value

def encode(value):
    return xor(value.encode('UTF-8')).hex()

def decode(coded_value):
    return xor(bytes.fromhex(coded_value)).decode('UTF-8')

def get_config_file():
    return Path(expanduser('~/.waltrc'))

def get_config_from_file():
    config_file = get_config_file()
    modified = False
    try:
        conf = load_conf(config_file, optional=True)
    except:
        print("Warning: %s file exists, but it could not be parsed properly." \
                            % config_file)
        conf = {}
    for key in conf:
        if key in CONFIG_CODED_ITEMS:
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
        config_file.write_text(self.printed())
        config_file.chmod(0o600)
        print('\nConfiguration was stored in %s.\n' % config_file)
    def add_item_group(self, desc, explain=None):
        self.item_groups.append(dict(
            desc    = desc,
            explain = explain,
            items   = []
        ))
    def add_item(self, key, value):
        comment = None
        if key in CONFIG_CODED_ITEMS:
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
        lines.append('')
        for item_group in self.item_groups:
            desc = item_group['desc']
            explain = item_group['explain']
            # add group-level comments
            lines.append('')
            self.comment_section(
                    lines,
                    '%s\n%s' % (desc, re.sub('.', '-', desc)))
            if explain:
                self.comment_section(
                    lines, explain)
            # add items
            for item in item_group['items']:
                key     = item['key']
                value   = item['value']
                comment = item['comment']
                if comment:
                    self.comment_section(lines, comment)
                # get yaml output for this item only
                # (by creating a temporary dictionary with just this item)
                item_and_value = yaml.dump({key:value})
                lines.append(item_and_value)
        return '\n'.join(lines) + '\n'

def save_config(conf):
    with ConfigFileSaver() as saver:
        if 'server' in conf:
            saver.add_item_group('ip or hostname of walt server')
            saver.add_item('server', conf['server'])
        if 'username' in conf:
            saver.add_item_group('credentials', explain=EXPLAIN_CREDEDENTIALS)
            saver.add_item('username', conf['username'])
            saver.add_item('password', conf['password'])

def set_conf(in_conf):
    global conf_dict
    conf_dict = in_conf

def reload_conf():
    set_conf(get_config_from_file())

class Conf(object):
    def __getitem__(self, key):
        return conf_dict[key]

conf_dict = None
conf = Conf()

