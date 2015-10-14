import sys
from multiprocessing import Process, Queue
from Queue import Empty

def confirm():
    while True:
        print 'Are you sure? (y/n):',
        res = raw_input()
        if res == 'y':
            return True
        if res == 'n':
            return False

class ProgressMessageThread(Process):
    def __init__(self, message):
        Process.__init__(self)
        self.message = message
        self.queue = Queue()
    def __enter__(self):
        self.start()
    def __exit__(self, type, value, traceback):
        self.queue.put(0)
        self.join()
    def print_status(self, status, termination='\r'):
        sys.stdout.write("%s %s%s" % (self.message, status, termination))
        sys.stdout.flush()
    def run(self):
        idx = 0
        try:
            while True:
                self.print_status("\\|/-"[idx])
                idx = (idx+1) % 4
                try:
                    self.queue.get(block = True, timeout = 0.2)
                except Empty:
                    continue
                # there is input in the queue, we should notify that we
                # are done and stop
                self.print_status("done", '\n')
                break
        except KeyboardInterrupt:
            self.queue.put(0)

