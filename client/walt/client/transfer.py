from walt.client.config import conf
from walt.client.tools import ProgressMessageThread
from walt.common.tcp import write_pickle, client_socket, \
                            Requests
from walt.common.constants import WALT_SERVER_TCP_PORT
import os, tarfile, socket
from walt.common.io import SmartBufferingFileReader


def run_transfer_with_image(client_operand_index, **kwargs):
    if client_operand_index == 0:
        req_id = Requests.REQ_TAR_TO_IMAGE
    else:
        req_id = Requests.REQ_TAR_FROM_IMAGE
    run_transfer(req_id = req_id,
                 client_operand_index = client_operand_index,
                 **kwargs)

def run_transfer_with_node(client_operand_index, **kwargs):
    if client_operand_index == 0:
        req_id = Requests.REQ_TAR_TO_NODE
    else:
        req_id = Requests.REQ_TAR_FROM_NODE
    run_transfer(req_id = req_id,
                 client_operand_index = client_operand_index,
                 **kwargs)

class SmartWriter:
    """SmartWriter class allows to write data on a socket while
       still keeping track of any data (typically error message)
       sent the other way."""
    def __init__(self, sock, sock_file):
        self.sock = sock
        self.f_r = SmartBufferingFileReader(sock_file)
        self.f_w = sock_file
        self.buf_out = ''
    def write(self, s):
        self.buf_out += self.f_r.read_available()
        return self.f_w.write(s)
    def wait_remote_close(self):
        while True:
            c = self.f_r.read(1)
            if c == '':
                break
            self.buf_out += c
    def shutdown_write(self):
        self.flush()
        self.sock.shutdown(socket.SHUT_WR)
    def flush(self):
        self.f_w.flush()
    def close(self):
        self.f_w.close()
    def get_msg(self):
        return self.buf_out.strip()

def run_transfer(req_id, dst_dir, dst_name, src_dir, src_name, tmp_name,
                            client_operand_index, **entity_params):
    params = dict(
        dst_dir = dst_dir,
        dst_name = dst_name,
        src_dir = src_dir,
        src_name = src_name,
        tmp_name = tmp_name,
        **entity_params
    )
    # connect to server
    s = client_socket(conf['server'], WALT_SERVER_TCP_PORT)
    f = s.makefile('r+', 0)
    # send the request id
    Requests.send_id(f, req_id)
    # wait for the READY message from the server
    f.readline()
    # write the parameters
    write_pickle(params, f)
    # handle client-side archiving / unarchiving
    with ProgressMessageThread('Transfering...') as message_thread:
        if client_operand_index == 0:
            # client is sending
            writer = SmartWriter(s, f)
            with tarfile.open(mode='w|', fileobj=writer, dereference=True) as archive:
                archive.add(os.path.join(src_dir, src_name), arcname=tmp_name)
            # let the other end know we are done writing
            writer.shutdown_write()
            # wait the other end to close
            writer.wait_remote_close()
            # ok done
            writer.close()
            # did we detect a message sent to us during the transfer?
            msg = writer.get_msg()
            if len(msg) > 0:
                # yes, interrupt the progress meter and print it
                message_thread.interrupt(msg)
        else:
            # client is receiving
            with tarfile.open(mode='r|', fileobj=f) as archive:
                archive.extractall(path=dst_dir)
            tmp_path = os.path.join(dst_dir, tmp_name)
            dst_path = os.path.join(dst_dir, dst_name)
            os.rename(tmp_path, dst_path)
    f.close()
    s.close()
