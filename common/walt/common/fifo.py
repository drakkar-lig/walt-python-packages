#!/usr/bin/env python
import os, stat, select
from walt.common.tools import failsafe_makedirs, fd_copy
from threading import Thread

RW_ALL = stat.S_IRUSR | stat.S_IWUSR | \
         stat.S_IRGRP | stat.S_IWGRP | \
         stat.S_IROTH | stat.S_IWOTH
BUFFER_SIZE = 1024

def failsafe_mkfifo(path, mode = None):
    if mode == None:
        mode = RW_ALL
    # check if it does not exist already
    if os.path.exists(path):
        return
    # ensure parent dir exists
    failsafe_makedirs(os.path.dirname(path))
    # create the fifo
    os.mkfifo(path)
    os.chmod(path, mode)

# fifos are special files.
# * when opening on one end, it will block until another process attempts to
#   open the other end.
# * when closed on one end, we should also close on the other end. For example,
#   if we are reading on /tmp/fifo and issuie 'echo test > /tmp/fifo' on another
#   terminal, we will receive 'test' but then we cannot start reading again
#   because the fifo has been closed on the 'echo' side. Instead, we should
#   close and re-open the fifo in order to get the next request.
# Because of that, we handle the fifo objects by running a dedicated thread
# that releases the main thread from fifo management work. The dedicated thread
# just dumps everything from the fifo to a pipe. The main thread reads the other
# end of this pipe. This allows the main thread to implement usual IO mechanisms
# (select(), etc.).

class ReadableFifo(object):
    def __init__(self, path):
        self.path = path
    def open(self):
        failsafe_mkfifo(self.path)
        data_r, data_w = os.pipe()
        ctrl_r, self.ctrl_w = os.pipe()
        t = Thread(target=self.reader_thread, args=(data_w, ctrl_r))
        t.start()
        self.file_r = os.fdopen(data_r, 'r', 0)
    def reader_thread(self, data_w, ctrl_r):
        should_stop = False
        while not should_stop:
            fifo_fd = os.open(self.path, os.O_RDONLY | os.O_NONBLOCK)
            fds = [fifo_fd, ctrl_r]
            while len(fds) == 2:
                r, w, e = select.select(fds,[],[])
                if fifo_fd in r:
                    fd_copy(fifo_fd, data_w, BUFFER_SIZE) or fds.remove(fifo_fd)
                else:
                    os.read(ctrl_r, 1)
                    should_stop = True
                    break
            os.close(fifo_fd)
        os.close(data_w)
        os.close(ctrl_r)
    def close(self):
        try:
            os.write(self.ctrl_w, 'X')
            os.close(self.ctrl_w)
        except:
            pass
        try:
            self.file_r.close()
        except:
            pass
    def __enter__(self):
        return self.file_r
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
    # redirect other accesses to self.file_r
    def __getattr__(self, attr):
        return getattr(self.file_r, attr)

def open_readable_fifo(path):
    fifo = ReadableFifo(path)
    fifo.open()
    return fifo

