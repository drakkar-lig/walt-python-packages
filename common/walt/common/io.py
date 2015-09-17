#!/usr/bin/env python
import os, sys
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

# The following class allows to read all
# chars pending in a file object.
class SmartBufferingFileReader(object):
    def __init__(self, in_file):
        self.in_file = in_file
        # timeout=0, do not block
        self.select_args = [[in_file],[],[in_file],0]
    def read_available(self):
        # continue reading until there
        # is nothing more to read
        s = ''
        while True:
            rlist, wlist, elist = select(*self.select_args)
            # error or no input (timeout), leave the loop
            if len(elist) > 0 or len(rlist) == 0:
                break
            try:
                c = self.in_file.read(1)
                if c == '':
                    break   # empty read
                s += c
            except:
                break
        return s
    def readline(self):
        return self.in_file.readline()

# Copy what's available from a SmartBufferingFileReader
# to an output stream
def read_and_copy(in_reader, out):
    buf = in_reader.read_available()
    if buf == '':
        return False    # close
    out.write(buf)
    out.flush()

