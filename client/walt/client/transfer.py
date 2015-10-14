from walt.client.config import conf
from walt.client.tools import ProgressMessageThread
from walt.common.tcp import write_pickle, client_socket, \
                            Requests
from walt.common.constants import WALT_SERVER_TCP_PORT
import os, tarfile

def run_transfer_with_image(session, dst_dir, dst_name, src_path,
                            client_operand_index, **kwargs):
    image_fullname, container_name = session.get_parameters()
    params = dict(
        container_name = container_name,
        image_fullname = image_fullname,
        dst_dir = dst_dir,
        dst_name = dst_name,
        src_dir = os.path.dirname(src_path),
        src_name = os.path.basename(src_path)
    )
    if client_operand_index == 0:
        req_id = Requests.REQ_TAR_TO_IMAGE
    else:
        req_id = Requests.REQ_TAR_FROM_IMAGE
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
    with ProgressMessageThread('Transfering...'):
        if client_operand_index == 0:
            # client is sending
            with tarfile.open(mode='w|', fileobj=f) as archive:
                archive.add(src_path, arcname=dst_name)
        else:
            # client is receiving
            with tarfile.open(mode='r|', fileobj=f) as archive:
                archive.extractall(path=dst_dir)
    f.close()
    s.close()
