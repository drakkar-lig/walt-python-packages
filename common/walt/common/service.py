class ServiceRequests:
    # the request id message may be specified directly as
    # as a decimal string (e.g. '4') or by the corresponding
    # name (e.g. 'REQ_NODE_CMD')
    @classmethod
    def get_id(cls, s):
        try:
            return int(s)
        except Exception:
            try:
                return getattr(cls, s)
            except Exception:
                return None


class GenericServer:
    def __init__(self):
        self.s = None
        self.listener_classes = {}

    def prepare(self, ev_loop):
        self.s = self.open_server_socket()
        self.join_event_loop(ev_loop)

    def join_event_loop(self, ev_loop):
        self.ev_loop = ev_loop
        ev_loop.register_listener(self)

    # let the event loop know what we are reading on
    def fileno(self):
        return self.s.fileno()

    def register_listener_class(self, req_id, cls, **ctor_args):
        self.listener_classes[req_id] = dict(cls=cls, ctor_args=ctor_args)

    def handle_event(self, ts):
        raise NotImplementedError  # should be handled in sub-classes

    def get_listener(self, req_id, **added_kwargs):
        if req_id is None or req_id not in self.listener_classes:
            print("Invalid request.")
            return None
        # create the appropriate listener given the req_id
        listener_info = self.listener_classes[req_id]
        cls = listener_info["cls"]
        ctor_args = listener_info["ctor_args"].copy()
        ctor_args.update(**added_kwargs)
        return cls(**ctor_args)

    def close(self):
        self.s.close()
