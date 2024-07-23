import select
import socket
import tarfile

from walt.client.link import connect_to_tcp_server
from walt.client.progress import ProgressMessageProcess
from walt.common.tcp import Requests, write_pickle, MyPickle as pickle


def run_transfer_with_image(client_operand_index, **kwargs):
    if client_operand_index == 0:
        req_id = Requests.REQ_TAR_TO_IMAGE
    else:
        req_id = Requests.REQ_TAR_FROM_IMAGE
    run_file_transfer(
        req_id=req_id, client_operand_index=client_operand_index, **kwargs
    )


def run_transfer_with_node(client_operand_index, **kwargs):
    if client_operand_index == 0:
        req_id = Requests.REQ_TAR_TO_NODE
    else:
        req_id = Requests.REQ_TAR_FROM_NODE
    run_file_transfer(
        req_id=req_id, client_operand_index=client_operand_index, **kwargs
    )


def run_transfer_for_image_build(src_dir, **kwargs):
    req_id = Requests.REQ_TAR_FOR_IMAGE_BUILD

    # we must record the directory entries at the root of the archive,
    # thus the arcname='' option.
    def add_archive_member(archive):
        archive.add(src_dir, arcname="", filter=set_root)

    def on_message(msg_thread, msg):
        if msg[0] == "stdout":
            msg_thread.print_stdout(msg[1])
        elif msg[0] == "stderr":
            msg_thread.print_stderr(msg[1])
        elif msg[0] == "retcode":
            return msg[1] == 0

    return run_transfer(
        req_id=req_id,
        client_operand_index=0,
        add_archive_member=add_archive_member,
        read_message=PickleMessageReader.read_message,
        on_message=on_message,
        progress_message=None,
        **kwargs
    )


class DefaultMessageReader:
    @staticmethod
    def read_message(sock_file):
        chunk = sock_file.read(4096)
        if len(chunk) == 0:
            return None
        else:
            return chunk.decode("utf-8")


class PickleMessageReader:
    @staticmethod
    def read_message(sock_file):
        try:
            return pickle.load(sock_file)
        except Exception:
            return None


class SmartWriter:
    """SmartWriter class allows to write data on a socket while
    still keeping track of any data (typically error message)
    sent the other way."""

    def __init__(self, sock_file, message_thread, read_message, on_message):
        self.sock_file = sock_file
        self.message_thread = message_thread
        self.read_message = read_message
        self.on_message = on_message
        self.ended = False
        self.status_ok = True

    def read_available(self, timeout=0):
        while not self.ended:
            r, w, e = select.select([self.sock_file], [], [], timeout)
            if len(r) == 0:
                return  # timed out
            msg = self.read_message(self.sock_file)
            if msg is None:
                self.ended = True
                return  # ended
            else:
                if self.on_message(self.message_thread, msg) is False:
                    self.status_ok = False
                    break
                continue

    def write(self, s):
        # poll for readable data
        self.read_available(0)
        return self.sock_file.write(s)

    def wait_remote_close(self):
        # use a loop with a small timeout to allow keyboard interrupts
        while not self.ended:
            self.read_available(0.1)

    def shutdown_write(self):
        self.flush()
        self.sock_file.shutdown(socket.SHUT_WR)

    def flush(self):
        self.sock_file.flush()

    def close(self):
        self.sock_file.close()

    def get_status(self):
        return self.status_ok


def set_root(tarinfo):
    tarinfo.uid = tarinfo.gid = 0
    tarinfo.uname = tarinfo.gname = "root"
    return tarinfo


def run_file_transfer(
    req_id, dst_dir, dst_name, src_path, client_operand_index, **entity_params
):
    params = dict(
        dst_dir=dst_dir, dst_name=dst_name, src_path=src_path, **entity_params
    )

    def add_archive_member(archive):
        archive.add(src_path, arcname=dst_name, filter=set_root)

    return run_transfer(req_id, client_operand_index, add_archive_member, **params)


def run_transfer(
    req_id,
    client_operand_index,
    add_archive_member,
    read_message=None,
    on_message=None,
    progress_message="Transfering...",
    **params
):
    # connect to server
    f = connect_to_tcp_server()
    # send the request id
    Requests.send_id(f, req_id)
    # wait for the READY message from the server
    f.readline()
    # write the parameters
    write_pickle(params, f)
    # handle client-side archiving / unarchiving
    try:
        with ProgressMessageProcess(progress_message) as message_thread:
            if client_operand_index == 0:
                # client is sending
                # ensure we know how to handle incoming messages
                if read_message is None:
                    read_message = DefaultMessageReader.read_message
                if on_message is None:

                    def on_message(msg_thd, msg):
                        return msg_thd.print_stdout(msg)

                writer = SmartWriter(f, message_thread, read_message, on_message)
                with tarfile.open(mode="w|", fileobj=writer) as archive:
                    add_archive_member(archive)
                # let the other end know we are done writing
                writer.shutdown_write()
                # wait the other end to close
                writer.wait_remote_close()
                # ok done
                writer.close()
                return writer.get_status()
            else:
                # client is receiving
                with tarfile.open(mode="r|", fileobj=f) as archive:
                    archive.extractall(path=params["dst_dir"])
                return True
    except OSError as e:
        print(e)
        return False
    finally:
        f.close()
