import sys, time
from walt.client.g5k.deploy.status import get_deployment_status
from walt.client.g5k.tools import printed_date_from_ts
from walt.common.formatting import columnate, framed

GENERAL_INFO_PATHS = {
    ('status',): str,
    ('start_date',): printed_date_from_ts,
    ('walltime',): str,
    ('vlan', 'type'): str,
    ('vlan', 'site'): str,
    ('vlan', 'vlan_id'): str,
    ('server', 'site'): str,
    ('server', 'g5k_env_file'): str,
    ('server', 'host'): str,
    ('sites', '*', 'job_id'): str,
    ('sites', '*', 'nodes'): lambda d: str(list(d)),
}

def print_path_value(info, path, print_func, passed=()):
    elem, next_elems = path[0], path[1:]
    if elem == '*':
        for elem in tuple(info.keys()):
            print_path_value(info, (elem,) + next_elems, print_func, passed)
        return
    if elem not in info:
        return
    info = info[elem]
    passed += (elem,)
    if len(next_elems) == 0:
        print('.'.join(passed) + ':', print_func(info))
    else:
        print_path_value(info, next_elems, print_func, passed)

def print_info():
    info = get_deployment_status()
    if info is None:
        print("No WalT platform is currently being deployed.", file=sys.stderr)
        sys.exit(1)
    for path, print_func in GENERAL_INFO_PATHS.items():
        print_path_value(info, path, print_func)
    ordered_history = sorted((ts, label) for (label, ts) in info['history'].items())
    start_date = info['start_date']
    prev_ts, prev_status, now = None, None, time.time()
    for ts, status in ordered_history:
        if ts < start_date:
            continue
        if ts > now:
            break
        if prev_ts != None:
            delay = int(ts - prev_ts)
            print(f'delays.{prev_status}: {delay} second(s)')
        prev_ts, prev_status = ts, status
