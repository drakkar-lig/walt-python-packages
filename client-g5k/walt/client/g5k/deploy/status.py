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
        status = 'init'
    )

def log_status_change(info, status, comment, verbose=False):
    if status == info['status'] and \
       len(info['log']) > 0 and info['log'][-1] == comment:
        return  # nothing changed
    info['log'].append(comment)
    if status != info['status']:
        info['status'] = status
        info['history'][status] = time.time()
    save_deployment_status(info)
    if verbose:
        print(comment + '...')

def main_job_is_active(info):
    server_site = info['server']['site']
    job_id = info['sites'][server_site].get('job_id')
    if job_id is None:
        return False
    out = run_cmd_on_site(info, server_site, f"oarstat -u -f -J".split())
    if out.strip() == '':
        return False
    active_jobs = json.loads(out)
    return str(job_id) in active_jobs

def get_deployment_status(err_out=True):
    try:
        info = json.loads(DEPLOYMENT_STATUS_FILE.read_text())
    except:
        if err_out:
            print(f'Could not read {DEPLOYMENT_STATUS_FILE}!', file=sys.stderr)
            sys.exit(1)
        return None
    if not main_job_is_active(info):
        return None
    # we recompute the 'status' from history
    # (it changes depending on whether we are before or after the scheduled start)
    last_ts, last_label, now = None, None, time.time()
    for (label, ts) in info['history'].items():
        if ts > now:
            continue
        if last_ts is None or last_ts < ts:
            last_ts, last_label = ts, label
    if last_label is not None:
        info['status'] = last_label
    return info

def forget_deployment():
    if DEPLOYMENT_STATUS_FILE.exists():
        DEPLOYMENT_STATUS_FILE.unlink()
