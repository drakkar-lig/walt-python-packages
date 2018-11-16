import sys, os
from multiprocessing import Process, Queue
from Queue import Empty

def yes_or_no(msg, okmsg = 'OK.\n', komsg = 'OK.\n'):
    while True:
        print '%s (y/n):' % msg,
        res = raw_input()
        if res == 'y':
            if okmsg:
                print okmsg
            return True
        elif res == 'n':
            if komsg:
                print komsg
            return False
        else:
            print 'Invalid response.'

def choose(msg='possible values:', **args):
    while True:
        print msg
        for k, explain in args.items():
            print "* %s: %s" % (k, explain)
        all_keys = '/'.join(args.keys())
        print 'selected value (%s):' % all_keys,
        res = raw_input()
        if res in args:
            return res
        else:
            print 'Invalid response.\n'

def confirm(msg = 'Are you sure?', komsg = 'Aborted.'):
    return yes_or_no(msg, komsg = komsg)

class ProgressMessageThread(Process):
    def __init__(self, message):
        Process.__init__(self)
        self.message = message
        self.queue = Queue()
    def __enter__(self):
        self.start()
        return self
    def __exit__(self, type, value, traceback):
        self.queue.put((0,))
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
                    req = self.queue.get(block = True, timeout = 0.2)
                except Empty:
                    continue
                # there is input in the queue
                if req[0] == 0:
                    # regular end: we should notify that we
                    # are done and stop
                    self.print_status("done", '\n')
                else:
                    # interruption: stop and print the provided msg.
                    sys.stdout.write("%s\n" % req[1])
                    sys.stdout.flush()
                break
        except KeyboardInterrupt:
            self.queue.put(0)
    def interrupt(self, msg):
        self.queue.put((1, msg))

