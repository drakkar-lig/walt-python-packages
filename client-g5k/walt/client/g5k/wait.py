# this is the code called by
# $ walt g5k wait
import time, sys
from walt.common.tools import BusyIndicator
from walt.client.g5k.deploy.status import get_deployment_status

def wait():
    busy_indicator = BusyIndicator('Analysing data')
    busy_indicator.start()
    prev_log_line = None
    while True:
        info = get_deployment_status()
        if info is None:
            busy_indicator.done()
            print("No WalT platform is currently being deployed.", file=sys.stderr)
            sys.exit(1)
        if info['status'] == 'ready':
            break
        # Several minutes are usually needed before the jobs
        # are really running on sites. Since walt-g5k-deploy-helper
        # is not called yet at this time, no log line is recorded when
        # passing the start date.
        # So in this case we print a more relevant message.
        if info['status'] == 'waiting.jobs':
            log_line = "Waiting for jobs startup"
        else:
            log_line = info['log'][-1]
        if log_line != prev_log_line:
            busy_indicator.set_label(log_line)
            prev_log_line = log_line
        busy_indicator.update()
        time.sleep(1)
    busy_indicator.done()
    print('Ready!')
