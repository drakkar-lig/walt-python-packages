# this is the code called by
# $ walt g5k wait
import sys
import time

from walt.client.g5k.deploy.status import (
    get_expiry_message,
    get_last_deployment_status,
    is_walltime_expired,
)
from walt.common.tools import BusyIndicator


def wait():
    busy_indicator = BusyIndicator("Analysing data")
    busy_indicator.start()
    prev_log_line, issue = None, None
    while True:
        first_time = prev_log_line is None
        info = get_last_deployment_status(allow_expired=True)
        if first_time and ((info is None) or is_walltime_expired(info)):
            issue = "No WalT platform is currently being deployed."
            break
        if info is None:
            issue = "Failed to read deployment.json!"
            break
        if info["status"] == "ready":
            break  # ok, we can stop waiting
        if "exception" in info:
            issue = info["exception"] + "\n" + "Deployment failure."
            break
        if is_walltime_expired(info):
            issue = "G5K job walltime ended before the deployment was complete."
            break
        if info["main_job_status"] == "ended":
            issue = "Deployment failure. " + get_expiry_message(info)
            break
        # Several minutes are usually needed before the jobs
        # are really running on sites. Since walt-g5k-deploy-helper
        # is not called yet at this time, no log line is recorded when
        # passing the start date.
        # So in this case we print a more relevant message.
        if info["status"] == "jobs.main.waiting":
            log_line = "Waiting for main job startup at " + info["server"]["site"]
        else:
            log_line = info["log"][-1]
        if log_line != prev_log_line:
            busy_indicator.set_label(log_line)
            prev_log_line = log_line
        busy_indicator.update()
        time.sleep(1)
    busy_indicator.done()
    if issue is not None:
        print(issue, file=sys.stderr)
        sys.exit(1)
    print("Ready!")
