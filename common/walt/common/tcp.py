import socket, cPickle as pickle

REQ_NEW_INCOMING_LOGS = 0
REQ_DUMP_LOGS = 1
REQ_SQL_PROMPT = 2
REQ_DOCKER_PROMPT = 3
REQ_NODE_SHELL = 4

def read_pickle(stream):
    try:
        return pickle.load(stream)
    except Exception as e:
        return None

def write_pickle(obj, stream):
    pickle.dump(obj, stream, pickle.HIGHEST_PROTOCOL)
    stream.flush()

def client_socket(host, port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((host, port))
    return s

def server_socket(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('', port))
    s.listen(1)
    return s

class TCPServer(object):
    def __init__(self, port):
        self.s = server_socket(port)
        self.listener_classes = {}

    def join_event_loop(self, ev_loop):
        self.ev_loop = ev_loop
        ev_loop.register_listener(self)

    # let the event loop know what we are reading on
    def fileno(self):
        return self.s.fileno()

    def register_listener_class(self, req_id, cls, **ctor_args):
        self.listener_classes[req_id] = dict(
            cls = cls,
            ctor_args = ctor_args
        )

    # when the event loop detects an event for us, this is 
    # what we will do: accept the tcp connection, read
    # the request and create the appropriate listener, 
    # and register this listener in the event loop.
    def handle_event(self):
        conn_s, addr = self.s.accept()
        sock_file = conn_s.makefile()
        req_id = read_pickle(sock_file)
        if req_id not in self.listener_classes:
            print 'Invalid request.'
            sock_file.close()
            conn_s.close()
            return
        # create the appropriate listener given the req_id
        listener_info = self.listener_classes[req_id]
        cls = listener_info['cls']
        ctor_args = listener_info['ctor_args'].copy()
        ctor_args.update(dict(
                    sock = conn_s,
                    sock_file = sock_file))
        listener = cls(**ctor_args)
        self.ev_loop.register_listener(listener)

    def close(self):
        self.s.close()

