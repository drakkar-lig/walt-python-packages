from time import time

class NodesClockSyncInfo:
    """ Walt nodes bootup synchronization handler.

        walt nodes get approximate time synchronization at
        bootup by requesting a unix timestamp from the server.
        It is of course possible (and recommended) to install a
        more precise synchronization protocol (preferably PTP)
        into the image.
    """
    def __init__(self, ev_loop):
        self.ev_loop = ev_loop
        self.tasks = {}

    def sync(self, task):
        # busybox can set date with only 1-second granularity,
        # so we wait until next second change before returning result.
        task.set_async()   # result will be available later
        task_id = id(task)
        self.tasks[task_id] = task
        # compute time of next second change
        target_ts = int(time() + 1)     # round to next int
        # plan event to be recalled at this time
        self.ev_loop.plan_event(
            ts = target_ts,
            target = self,
            task_id = task_id,
            target_ts = target_ts
        )

    def handle_planned_event(self, task_id, target_ts):
        # return timestamp and unblock the node
        self.tasks[task_id].return_result(target_ts)
        # cleanup
        del self.tasks[task_id]
