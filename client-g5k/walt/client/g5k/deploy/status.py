import json
import sys
import time
from pathlib import Path

DEPLOYMENT_STATUS_DIRECTORY = Path.home() / ".walt-g5k" / "deployments"
LAST_DEPLOYMENT_STATUS_FILE = DEPLOYMENT_STATUS_DIRECTORY / "last-deployment.json"


def get_status_file(deployment_id):
    return DEPLOYMENT_STATUS_DIRECTORY / deployment_id / "deployment.json"


def save_deployment_status(info, update_link=False):
    status_file = get_status_file(info["deployment_id"])
    if not status_file.parent.exists():
        status_file.parent.mkdir(parents=True)
    # status will be recomputed on reload from history
    clean_info = {k: v for (k, v) in info.items() if k != "status"}
    status_file.write_text(json.dumps(clean_info) + "\n")
    if update_link:
        LAST_DEPLOYMENT_STATUS_FILE.unlink(missing_ok=True)
        LAST_DEPLOYMENT_STATUS_FILE.symlink_to(str(status_file))


def init_status_info(info, deployment_id):
    info.update(
        deployment_id=deployment_id,
        log=[],
        history={},
        status="init",
        main_job_status="init",
    )
    save_deployment_status(info, update_link=True)


def log_status_change(info, status, comment, verbose=False):
    prev_status = info.get("status")
    if status == prev_status and len(info["log"]) > 0 and info["log"][-1] == comment:
        return  # nothing changed
    info["log"].append(comment)
    if status != prev_status:
        info["status"] = status
        info["history"][status] = time.time()
    save_deployment_status(info)
    if verbose:
        print(comment + "...")
        sys.stdout.flush()


def record_main_job_startup(info):
    info["main_job_status"] = "running"
    log_status_change(
        info, "jobs.main.startup", "Starting main job at " + info["server"]["site"]
    )


def record_main_job_ending(info, e=None):
    info["main_job_status"] = "ended"
    if e is not None:
        info["exception"] = str(e)
    log_status_change(
        info, "jobs.main.ending", "Ending main job at " + info["server"]["site"]
    )


def is_expired(info, now=None):
    return get_expiry_message(info, now=now) is not None


def is_walltime_expired(info, now=None):
    if now is None:
        now = time.time()
    return now >= info["end_date"]


def get_expiry_message(info, now=None):
    if is_walltime_expired(info, now=now):
        return "G5K deployment ended its walltime."
    if info["main_job_status"] == "ended":
        logs_dir = info["logs_dir"]
        return f"Main G5K deployment job ended (see {logs_dir})."


def fix_info(info, allow_expired):
    now = time.time()
    if is_expired(info, now=now):
        if not allow_expired:
            return None
        info["status"] = "expired"
        return info
    else:
        # we recompute the 'status' from history
        # (it changes depending on whether we are before or after the scheduled start)
        last_ts, last_label = None, None
        for label, ts in info["history"].items():
            if ts > now:
                continue
            if last_ts is None or last_ts < ts:
                last_ts, last_label = ts, label
        if last_label is not None:
            info["status"] = last_label
        return info


def load_status_file(status_file, allow_expired):
    if not status_file.exists():
        return None
    info = None
    for i in range(5):
        try:
            info = json.loads(LAST_DEPLOYMENT_STATUS_FILE.read_text())
            break
        except Exception:
            time.sleep(1)  # then retry
    if info is None:
        return None
    return fix_info(info, allow_expired)


def get_last_deployment_status(allow_expired=False):
    return load_status_file(LAST_DEPLOYMENT_STATUS_FILE, allow_expired)


def get_deployment_status(deployment_id):
    status_file = get_status_file(deployment_id)
    return load_status_file(status_file, True)


def record_end_of_deployment(info):
    info["end_date"] = time.time()
    save_deployment_status(info)


def exit_if_walt_platform_deployed():
    info = get_last_deployment_status()
    if info is not None:
        print("A walt platform is already deployed.")
        print("Use 'walt g5k release' to release this existing deployment.")
        sys.exit(1)
