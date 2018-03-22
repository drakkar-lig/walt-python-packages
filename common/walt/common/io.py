#!/usr/bin/env python
import os, sys, socket
from select import select

# This function allows to disable buffering
# of a file.
# CAUTION:
# * doing this may cause data loss if some
#   data is available to be read at the time
#   unbuffered() is called.
#   A kind of synchronization with the other
#   end can prevent this issue.
# * since we use the fileno() method,
#   this will not work when called on a remote
#   (RPyC) object (the filedescriptor integer
#   is only relevant on the local machine...)
def unbuffered(f, mode):
    # we need to duplicate the filedescriptor
    # in order to avoid the same filedescriptor
    # to be closed several times
    return os.fdopen(os.dup(f.fileno()), mode, 0)

# SmartFile objects provide an additional read_available() method
# allowing to read all chars pending without blocking.
class SmartFile(object):
    BUFFER_SIZE = 1024 * 10
    def __init__(self, file_r, file_w = None):
        self.file_r = file_r
        self.file_w = file_w
        # timeout=0, do not block
        self.select_args = [[file_r],[],[file_r],0]
        self.chars = [ '' ] * SmartFile.BUFFER_SIZE
    def read_available(self):
        # continue reading until there
        # is nothing more to read or we reach BUFFER_SIZE
        chars = self.chars
        try:
            for i in xrange(SmartFile.BUFFER_SIZE):
                rlist, wlist, elist = select(*self.select_args)
                # error or no input (timeout), leave the loop
                if len(elist) > 0 or len(rlist) == 0:
                    i -= 1
                    break
                chars[i] = self.file_r.read(1)
                if chars[i] == '':
                    break   # empty read
        except:
            chars[i] = ''
        return ''.join(chars[:i+1])
    def __getattr__(self, attr):
        if attr in ('write', 'flush'):
            f = self.file_w
        else:
            f = self.file_r
        return getattr(f, attr)
    @property
    def closed(self):
        return self.file_r is None
    def close(self):
        if self.file_r is not None:
            self.file_r.close()
            self.file_r = None
        if self.file_w is not None:
            self.file_w.close()
            self.file_w = None
    def __del__(self):
        self.close()

# Copy what's available from a SmartFile
# to an output stream
def read_and_copy(in_reader, out):
    try:
        buf = in_reader.read_available()
        if buf == '':
            return False    # close
        out.write(buf)
        out.flush()
    except socket.error:
        return False    # close

