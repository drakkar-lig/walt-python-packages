import os
import socket


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


# Copy what's available from a file
# to an output stream
def read_and_copy(in_reader, out):
    try:
        buf = in_reader.read(4096)
        if buf == b"":
            return False  # close
        out.write(buf)
        out.flush()
    except socket.error:
        return False  # close
