import json, sys, time
from pathlib import Path
from walt.client.g5k.myexeco import load_execo_g5k
from walt.client.g5k.tools import run_cmd_on_site

DEPLOYMENT_STATUS_FILE = Path.home() / '.walt-g5k' / 'deployment.json'

def save_deployment_status(info):
    if not DEPLOYMENT_STATUS_FILE.parent.exists():
        DEPLOYMENT_STATUS_FILE.parent.mkdir(parents=True)
    # status will be recomputed on reload from history
    clean_info = {k:v for (k,v) in info.items() if k !='status'}
    DEPLOYMENT_STATUS_FILE.write_text(json.dumps(clean_info) + '\n')

def init_status_info(info):
    info.update(
        log = [],
        history = {},
        status = 'init',
        main_job_status = 'init'
    )

def log_status_change(info, status, comment, verbose=False):
    prev_status = info.get('status')
    if status == prev_status and \
       len(info['log']) > 0 and info['log'][-1] == comment:
        return  # nothing changed
    info['log'].append(comment)
    if status != prev_status:
        info['status'] = status
        info['history'][status] = time.time()
    save_deployment_status(info)
    if verbose:
        print(comment + '...')
        sys.stdout.flush()

def record_main_job_startup():
    info = get_raw_deployment_status()
    info['main_job_status'] = 'running'
    log_status_change(info, 'jobs.main.startup', 'Starting main job at ' + info['server']['site'])

def record_main_job_ending(e = None):
    info = get_raw_deployment_status()
    info['main_job_status'] = 'ended'
    if e is not None:
        info['exception'] = str(e)
    log_status_change(info, 'jobs.main.ending', 'Ending main job at ' + info['server']['site'])

def is_expired(info, now=None):
    return get_expiry_message(info, now=now) is not None

def is_walltime_expired(info, now=None):
    if now is None:
        now = time.time()
    return (now >= info['end_date'])

def get_expiry_message(info, now=None):
    if is_walltime_expired(info, now=now):
        return 'G5K deployment ended its walltime.'
    if info['main_job_status'] == 'ended':
        return 'Main G5K deployment job ended (see ~/.walt-g5k/logs/deploy.* at %s).' \
                    % info['server']['site']

def get_raw_deployment_status():
    if not DEPLOYMENT_STATUS_FILE.exists():
        return None
    for i in range(5):
        try:
            return json.loads(DEPLOYMENT_STATUS_FILE.read_text())
        except:
            time.sleep(1)  # then retry
    return None

def get_deployment_status(allow_expired=False):
    info = get_raw_deployment_status()
    if info is None:
        return None
    now = time.time()
    if is_expired(info, now=now):
        if not allow_expired:
            return None
        info['status'] = 'expired'
        return info
    else:
        # we recompute the 'status' from history
        # (it changes depending on whether we are before or after the scheduled start)
        last_ts, last_label = None, None
        for (label, ts) in info['history'].items():
            if ts > now:
                continue
            if last_ts is None or last_ts < ts:
                last_ts, last_label = ts, label
        if last_label is not None:
            info['status'] = last_label
        return info

def record_end_of_deployment():
    info = get_raw_deployment_status()
    if info is not None:
        info['end_date'] = time.time()
        save_deployment_status(info)

def exit_if_walt_platform_deployed():
    info = get_deployment_status()
    if info is not None:
        print("A walt platform is already deployed.")
        print("Use 'walt g5k release' to release this existing deployment.")
        sys.exit(1)
