import json
from os.path import expanduser

CONF_ITEMS = dict(
    server = dict(
        desc='ip or hostname of walt server',
        itemtype=str,
        default='localhost'
    )
)

def ask_config(key):
    infos = CONF_ITEMS[key]
    desc = infos['desc']
    default = infos['default']
    itemtype = infos['itemtype']
    print 'Missing configuration item:', desc
    msg = 'please enter it now [%s]: ' % str(default)
    while True:
        value = raw_input(msg)
        if value.strip() == '':
            value = default
            break
        try:
            value = itemtype(value)
            break
        except:
            print "Bad input: expected type is '%s'" % str(itemtype)
    print 'Selected value:', str(value)
    return value

def get_config():
    config_file = expanduser('~/walt.conf')
    conf = None
    modified = False
    try:
        with open(config_file) as f:
            conf = json.load(f)
    except:
        pass
    if not isinstance(conf, dict):
        conf = {}
        modified = True
    for key in CONF_ITEMS:
        if key not in conf:
            conf[key] = ask_config(key)
            modified = True
    if modified:
        with open(config_file, 'w') as f:
            json.dump(conf, f, indent=4)
            print 'Configuration was stored in %s.' % config_file
    return conf

conf = get_config()

