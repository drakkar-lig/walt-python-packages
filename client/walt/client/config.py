import json, re
from os.path import expanduser
from collections import OrderedDict

SINGLE_ITEM=1
ONE_OR_MORE_ITEMS=2

CONF_ITEMS = OrderedDict([
    ('server', dict(
        desc='ip or hostname of walt server',
        itemtype=str,
        default='localhost',
        user_input=True
    )),
    ('username', dict(
        desc='walt username',
        explain='''\
This name is used to indicate the author of the walt images you create.
If you have an account on the docker hub, you should input the same username,
because walt looks for any walt image stored there.
Otherwise you are free to choose the one you want.''',
        itemtype=str,
        default=None,
        user_input=True
    ))
])

def ask_config(key):
    infos = CONF_ITEMS[key]
    desc = infos['desc']
    default = infos['default']
    itemtype = infos['itemtype']
    print
    print 'Missing configuration item:', desc
    if 'explain' in infos:
        print infos['explain']
    if default:
        msg = 'please enter it now [%s]: ' % str(default)
    else:
        msg = 'please enter it now: '
    while True:
        value = raw_input(msg)
        if value.strip() == '':
            if default:
                value = default
                print 'Selected value:', str(value)
                break
            else:
                continue
        try:
            value = itemtype(value)
            break
        except:
            print "Bad input: expected type is '%s'" % str(itemtype)
    return value

def get_config_file():
    return expanduser('~/walt.conf')

# Note: json comments are not allowed in the standard
# and thus not handled in the json python module.
# We handle them manually.
def get_config(config_file):
    conf = None
    modified = False
    try:
        with open(config_file) as f:
            # filter out comments
            filtered = re.sub('#.*', '', f.read())
            # read valid json
            conf = json.loads(filtered, object_pairs_hook=OrderedDict)
    except:
        pass
    if not isinstance(conf, OrderedDict):
        conf = OrderedDict()
        modified = True
    for key in CONF_ITEMS:
        if key not in conf:
            if CONF_ITEMS[key]['user_input']:
                conf[key] = ask_config(key)
            else:
                conf[key] = CONF_ITEMS[key]['default']
            modified = True
    if modified:
        save_config(conf, config_file)
        print '\nConfiguration was stored in %s.\n' % config_file
    return conf

def save_config(conf, config_file):
    lines=[ ]
    for k in conf:
        # if not the 1st item add ',' before continuing
        if len(lines) > 0:
            lines = lines[0:-1] + [ lines[-1] + ',' ]
        # add item label and description as 'json comments'
        infos = CONF_ITEMS[k]
        lines.append('')
        lines.append('    # %s' % infos['desc'])
        lines.append('    # %s' % re.sub('.', '-', infos['desc']))
        if 'explain' in infos:
            lines.extend([ '    # ' + line for line in infos['explain'].splitlines() ])
        # get json output for this item only
        # (by creating a temporary dictionary with just this item)
        item_and_value = json.dumps({k:conf[k]}, indent=4).splitlines()[1:-1]
        lines.extend(item_and_value)
    # concatenate all and write the file
    with open(config_file, 'w') as f:
        f.write('{' + '\n'.join(lines) + '\n}\n')

conf_path = get_config_file()
conf = get_config(conf_path)

