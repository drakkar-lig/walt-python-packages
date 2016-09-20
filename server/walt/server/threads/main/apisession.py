
class APISession(object):

    SESSIONS = {}
    TARGET_APIS = {}

    @staticmethod
    def register_target_api(name, cls):
        APISession.TARGET_APIS[name] = cls

    @staticmethod
    def get(server, task):
        link_id = task.link_info.link_id
        if link_id not in APISession.SESSIONS:
            cls = APISession.TARGET_APIS[task.target_api]
            APISession.SESSIONS[link_id] = cls(task, server)
        return APISession.SESSIONS[link_id]

    def __init__(self, first_task, server):
        self.session_objects = set()
        self.server, self.images, self.devices, self.nodes, self.logs = \
            server, server.images, server.devices, server.nodes, server.logs
        linfo = first_task.link_info
        self.link_id, self.requester, self.remote_ip = \
            linfo.link_id, linfo.requester, linfo.remote_ip

    def run(self, t):
        # get task info
        attr, args, kwargs_items = t.desc()
        # rebuild kwargs
        # (t did not returned a dict, this is would involve rpyc calls again)
        kwargs = { k:v for k, v in kwargs_items }
        # lookup task
        m = getattr(self, attr)
        # run task
        res = m(*args, **kwargs)
        # return result
        t.return_result(res)

    def register_session_object(self, obj):
        self.session_objects.add(obj)

    def on_connect(self):
        print 'session %d: %s just connected' % (self.link_id, self.requester.username)

    def on_disconnect(self):
        print 'session %d: disconnected' % self.link_id
        for obj in self.session_objects:
            obj.cleanup()
        del APISession.SESSIONS[self.link_id]

