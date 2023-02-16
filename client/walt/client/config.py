import yaml, re, os, socket
from walt.client.plugins import get_hook
from walt.client.tools import yes_or_no
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

CONFIG_CODED_ITEMS=[('hub', 'password')]

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
    p = Path(expanduser('~/.walt/config'))
    if not p.exists():
        legacy_p = Path(expanduser('~/.waltrc'))
        if legacy_p.exists():
            p.parent.mkdir(exist_ok=True)
            legacy_p.rename(p)
            p.chmod(0o600)
    return p

def get_config_from_file():
    config_file = get_config_file()
    try:
        conf_dict = load_conf(config_file, optional=True)
        if conf_dict is None:
            return {}, False
    except:
        print("Warning: %s file exists, but it could not be parsed properly." \
                            % config_file)
        return {}, False
    # handle legacy conf items
    updated = False
    if 'walt' not in conf_dict or not isinstance(conf_dict['walt'], dict):
        conf_dict['walt'] = {}
    if 'hub' not in conf_dict or not isinstance(conf_dict['hub'], dict):
        conf_dict['hub'] = {}
    if 'server' in conf_dict:
        conf_dict['walt']['server'] = conf_dict.pop('server')
        updated = True
    if 'username' in conf_dict:
        conf_dict['walt']['username'] = conf_dict.pop('username')
        # walt and hub usernames were previously always the same
        conf_dict['hub']['username'] = conf_dict['walt']['username']
        updated = True
    if 'password' in conf_dict:
        conf_dict['hub']['password'] = conf_dict.pop('password')
        updated = True
    if len(conf_dict['walt']) == 0:
        del conf_dict['walt']
    if len(conf_dict['hub']) == 0:
        del conf_dict['hub']
    # decode coded items
    for group_name, items in conf_dict.items():
        for key in list(items):
            if (group_name, key) in CONFIG_CODED_ITEMS:
                conf_dict[group_name][key] = decode(conf_dict[group_name][key])
    return conf_dict, updated

class ConfigFileSaver(object):
    def __init__(self):
        self.item_groups = []
    def __enter__(self):
        return self
    def __exit__(self, type, value, tb):
        # concatenate all and write the file
        config_file = get_config_file()
        config_file.parent.mkdir(exist_ok=True)
        config_file.write_text(self.printed())
        config_file.chmod(0o600)
        print('\nConfiguration was updated in %s.\n' % config_file)
    def add_item_group(self, name, desc, explain=None):
        self.item_groups.append(dict(
            name    = name,
            desc    = desc,
            explain = explain,
            items   = []
        ))
    def add_item(self, key, value, comment = None):
        group_name = self.item_groups[-1]['name']
        if (group_name, key) in CONFIG_CODED_ITEMS:
            new_comment = '(%s value is encoded.)' % key
            comment = new_comment if comment is None else f'{comment} {new_comment}'
            value   = encode(value)
        self.item_groups[-1]['items'].append(dict(
            key     = key,
            value   = value,
            comment = comment
        ))
    def comment_section(self, lines, section, indent=0):
        return lines.extend(self.indent_lines(
                self.comment_lines(section.splitlines()), indent))
    def comment_lines(self, lines):
        return [ '# ' + line for line in lines ]
    def indent_lines(self, lines, indent):
        return [ (' ' * indent) + line for line in lines ]
    def printed(self):
        lines = [ '' ]
        self.comment_section(lines, CONFIG_FILE_TOP_COMMENT)
        lines.append('')
        for item_group in self.item_groups:
            name = item_group['name']
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
            # add group name
            lines.append(f'{name}:')
            # add items
            for item in item_group['items']:
                key     = item['key']
                value   = item['value']
                comment = item['comment']
                if comment:
                    self.comment_section(lines, comment, 4)
                # get yaml output for this item only
                # (by creating a temporary dictionary with just this item)
                item_and_value = yaml.dump({key:value}).strip()
                lines.append(f'    {item_and_value}')
        return '\n'.join(lines) + '\n\n'

def save_config():
    with ConfigFileSaver() as saver:
        if 'walt' in conf_dict:
            saver.add_item_group('walt', 'WalT platform')
            if 'server' in conf_dict['walt']:
                saver.add_item('server', conf_dict['walt']['server'],
                               'IP or hostname of WalT server')
            if 'username' in conf_dict['walt']:
                saver.add_item('username', conf_dict['walt']['username'],
                               'WalT user name used to identify your work')
        if 'hub' in conf_dict:
            saver.add_item_group('hub', 'Docker Hub credentials')
            if 'username' in conf_dict['hub']:
                saver.add_item('username', conf_dict['hub']['username'])
            if 'password' in conf_dict['hub']:
                saver.add_item('password', conf_dict['hub']['password'])

def set_conf(in_conf):
    global conf_dict
    conf_dict = in_conf

def reload_conf():
    conf_dict, should_rewrite = get_config_from_file()
    set_conf(conf_dict)
    if should_rewrite:
        save_config()

def resolve_new_user():
    server_check = 'server' not in conf_dict['walt']
    if server_check:
        hook = get_hook('config_missing_server')
        if hook is not None:
            server_check = hook()
    print('You are a new user of this WalT platform, and this command requires a few configuration items.')
    while True:
        server_update = 'server' not in conf_dict['walt']
        username_update = 'username' not in conf_dict['walt']
        if server_update:
            conf_dict['walt']['server'] = ask_config_item('IP or hostname of WalT server')
        if username_update:
            use_hub = yes_or_no('Do you intend to push or pull images to/from the docker hub?',
                                okmsg=None, komsg=None)
            if use_hub:
                if 'hub' not in conf_dict:
                    conf_dict['hub'] = {}
                print('Please get an account at hub.docker.com if not done yet, then specify credentials here.')
                conf_dict['hub'].update(
                        username = ask_config_item('username'),
                        password = ask_config_item('password', coded=True))
                conf_dict['walt']['username'] = conf_dict['hub']['username']
            else:
                conf_dict['walt']['username'] = ask_config_item('Please choose a username for this walt platform')
        server_error, hub_error = test_config(use_hub)
        if not server_error and not hub_error:
            break   # OK done
        if hub_error:
            # walt username was copied from hub username, but hub credentials are wrong
            # so forget it
            del conf_dict['walt']['username']
        continue  # prompt again to user
    if use_hub:
        username = conf_dict['walt']['username']
        print(f'Note: {username} will also be your username on the WalT platform.')

def resolve_hub_creds():
    print('Docker hub credentials are missing or invalid. Please enter them below.')
    while True:
        conf_dict['hub'].update(
                    username = ask_config_item('username'),
                    password = ask_config_item('password', coded=True))
        if test_config(True):
            break

class ConfTree:
    class walt:
        class server:
            @staticmethod
            def resolve():
                resolve_new_user()
        class username:
            @staticmethod
            def resolve():
                resolve_new_user()
    class hub:
        class username:
            @staticmethod
            def resolve():
                resolve_hub_creds()
        class password:
            @staticmethod
            def resolve():
                resolve_hub_creds()

def init_config(link_cls):
    global server_link_cls
    server_link_cls = link_cls

def test_config(credentials_check):
    # we try to establish a connection to the server,
    # and optionaly to connect to the docker hub.
    # the return value is a tuple of 2 elements telling
    # whether a server connection or a hub credentials error
    # occured.
    print()
    print('Testing provided configuration...')
    if server_link_cls is None:
        raise Exception('test_config() called but server_link_cls not known yet.')
    try:
        with server_link_cls() as server:
            if credentials_check:
                with server.set_busy_label('Authenticating to the docker hub'):
                    if not server.hub_login():
                        print()
                        del conf_dict['hub']['username']
                        del conf_dict['hub']['password']
                        return False, True
    except socket.error:
        print('FAILED. The value of \'walt.server\' you entered seems invalid (or the server is down?).')
        print()
        del conf_dict['walt']['server']
        return True, False
    print('OK.')
    print()
    return False, False

server_link_cls = None
conf_dict = None

class Conf:
    def __init__(self, path=()):
        self._path = path
    def __repr__(self):
        return '<Configuration: ' + repr(self._analyse_path(self._path)) + '>'
    def _do_lazyload(self):
        if conf_dict is None:
            reload_conf()
    def _analyse_path(self, path):
        self._do_lazyload()
        conf_tree, conf_obj, cur_path = ConfTree, conf_dict, ()
        for attr in path:
            cur_path += (attr,)
            conf_tree = getattr(conf_tree, attr, None)
            if conf_tree is None:
                conf_item_str = 'conf.' + '.'.join(cur_path)
                raise Exception(f'Unexpected conf item: {conf_item_str}')
            if hasattr(conf_tree, 'resolve'):
                # leaf value
                if attr in conf_obj:
                    return { 'type': 'present-leaf', 'value': conf_obj[attr] }
                else:
                    def resolve():
                        conf_tree.resolve()
                        save_config()
                    return { 'type': 'missing-leaf', 'resolve': resolve }
            else:
                # category node
                if not attr in conf_obj:
                    conf_obj[attr] = {}
            conf_obj = conf_obj[attr]
        return { 'type': 'category', 'value': conf_obj }
    # we use point-based notation (e.g., conf.walt.server)
    def __getattr__(self, attr):
        path = self._path + (attr,)
        path_info = self._analyse_path(path)
        if path_info['type'] == 'present-leaf':
            return path_info['value']
        elif path_info['type'] == 'missing-leaf':
            path_info['resolve']()
            return self.__getattr__(attr)   # redo
        else:   # category
            return Conf(path)
    def __hasattr__(self, attr):
        path = self._path + (attr,)
        path_info = self._analyse_path(path)
        return path_info['type'] != 'missing-leaf'
    def __setattr__(self, attr, v):
        if attr in ('_path',):
            self.__dict__[attr] = v
            return
        cat_path_info = self._analyse_path(self._path)
        item_path_info = self._analyse_path(self._path + (attr,))
        assert cat_path_info['type'] == 'category'
        assert item_path_info['type'] in ('present-leaf', 'missing-leaf')
        cat_path_info['value'][attr] = v

conf = Conf()

