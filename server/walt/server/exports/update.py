import os
import pickle
import sys
from contextlib import contextmanager

from walt.server.exports import exports
from walt.server.tools import serialized
from walt.server.exports.const import TFTP_ROOT

UPDATE_EXPORTS_QUEUE_PATH = TFTP_ROOT / "update-exports-queue.pickle"

UPDATE_EXPORTS_QUEUE_LOCK_PATH = TFTP_ROOT / "update-exports-queue.lock"
UPDATE_EXPORTS_LOCK_PATH = TFTP_ROOT / "update-exports.lock"


@contextmanager
def access_queue():
    with serialized(UPDATE_EXPORTS_QUEUE_LOCK_PATH):
        if UPDATE_EXPORTS_QUEUE_PATH.exists():
            queue = pickle.loads(UPDATE_EXPORTS_QUEUE_PATH.read_bytes())
        else:
            queue = []
        saved_queue = queue.copy()
        print(os.getpid(), "read", queue)
        yield queue
        if queue != saved_queue:
            print(os.getpid(), "update", queue)
            UPDATE_EXPORTS_QUEUE_PATH.write_bytes(pickle.dumps(queue))


def run():
    if len(sys.argv) != 2 or \
            sys.argv[1] not in ('prepare', 'update', 'cleanup'):
        sys.exit(f"USAGE: {sys.argv[0]} [prepare|update|cleanup]")

    TFTP_ROOT.mkdir(parents=True, exist_ok=True)
    if sys.argv[1] == "prepare":
        with serialized(UPDATE_EXPORTS_LOCK_PATH):
            exports.prepare()
    elif sys.argv[1] == "update":
        # we have a system of locks allowing to cancel useless update
        # calls. For instance, if we have 3 calls C1, C2 and C3 in a
        # short period of time, then:
        # 1. C1 runs.
        # 2. C2 blocks until C1 ends, C3 blocks until C1 and C2 end.
        # 3. C2 runs and cancels C3.
        # We can cancel C3 because this update was called before
        # C2 could run, so we can assume the update of exports
        # it was supposed to handle have been detected and handled
        # by C2.
        pid = os.getpid()
        # record that this pid is waiting to run
        with access_queue() as queue:
            queue.append(pid)
        with serialized(UPDATE_EXPORTS_LOCK_PATH):
            # now that we got the lock, check how is the queue
            # when we are about to start the process:
            # * if we are no longer in the queue, this means
            #   another run did the job and cancelled this job,
            #   so we can exit right away.
            # * otherwise, record the length of the queue to
            #   know which calls we can cancel later.
            with access_queue() as queue:
                if pid not in queue:
                    print(os.getpid(), "cancelled")
                    return
                queue_len = len(queue)
            print(os.getpid(), "starting queue_len =", queue_len)
            exports.update()
            # we are done, so we can:
            # * remove this run from the queue
            # * cancel any other run which was requested before we started
            with access_queue() as queue:
                # note: we use this notation to remove in-place;
                # we have to keep the same queue object for letting
                # access_queue() detect we changed it.
                del queue[:queue_len]
    elif sys.argv[1] == "cleanup":
        # cancel any pending update
        with access_queue() as queue:
            del queue[:]
        # call cleanup function
        with serialized(UPDATE_EXPORTS_LOCK_PATH):
            exports.cleanup()


if __name__ == "__main__":
    run()
