
def lookup_server_ip():
    with open('/proc/cmdline') as f:
        for t in [ elem.split('=') for elem in f.read().split() ]:
            if t[0] == 'nfs_server':
                return t[1]
