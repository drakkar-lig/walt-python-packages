#!/usr/bin/env python
import socket, time, sys
from walt.client import config
from walt.client.link import ClientToServerLink
from walt.client.auth import get_auth_conf

EXPLAIN_CREDEDENTIALS='''\
These credentials must match your account at hub.docker.com.
The username will also be used to identify your work on the WalT platform.'''

def save_config(conf):
    with config.ConfigFileSaver() as saver:
        saver.add_item_group('ip or hostname of walt server')
        saver.add_item('server', conf['server'])
        saver.add_item_group('credentials', explain=EXPLAIN_CREDEDENTIALS)
        saver.add_item('username', conf['username'])
        saver.add_item('password', conf['password'], coded=True)

def init_config():
    try:
        conf = config.get_config_from_file(coded_items=['password'])
        modified = False
        server_check = 'server' not in conf
        credentials_check = 'username' not in conf or 'password' not in conf
        if server_check or credentials_check:
            print "Starting configuration procedure..."
        while True:
            server_update = 'server' not in conf
            credentials_update = 'username' not in conf or 'password' not in conf
            if server_update:
                conf['server'] = config.ask_config_item('ip or hostname of WalT server')
            if credentials_update:
                print 'Docker hub credentials are missing, incomplete or invalid.'
                print '(Please get an account at hub.docker.com if not done yet.)'
            if 'username' not in conf:
                conf['username'] = config.ask_config_item('username')
            if 'password' not in conf:
                conf['password'] = config.ask_config_item('password', coded=True)
            if server_check or credentials_check:
                modified = True
                if test_config(conf, credentials_check):
                    break   # ok, leave the loop
            else:
                break
        if modified:
            save_config(conf)
        if server_check or credentials_check:
            print 'Resuming normal operations...'
            time.sleep(2)
        config.set_conf(conf)
    except KeyboardInterrupt:
        print '\nAborted.'
        sys.exit()

def test_config(conf, credentials_check):
    # we try to establish a connection to the server,
    # and optionaly to connect to the docker hub.
    config.set_conf(conf)
    try:
        with ClientToServerLink() as server:
            if credentials_check:
                server.set_busy_label('Authenticating to the docker hub')
                auth_conf = get_auth_conf(server)
                if not server.docker_login(auth_conf):
                    print 'Re-trying...'
                    del conf['username']
                    del conf['password']
                    return False
    except socket.error:
        print 'Network connection to WalT server failed.'
        print 'The value of \'server\' you entered seems invalid (or the server is down?). Re-trying...'
        del conf['server']
        return False
    return True

