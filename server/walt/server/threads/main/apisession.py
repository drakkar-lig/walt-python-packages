
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

    @staticmethod
    def cleanup_all():
        for session in APISession.SESSIONS.values():
            session.cleanup()

    def __init__(self, first_task, server):
        self.session_objects = []
        self.server, self.images, self.devices, self.nodes, self.logs = \
            server, server.images, server.devices, server.nodes, server.logs
        linfo = first_task.link_info
        self.link_id, self.remote_api, self.remote_ip = \
            linfo.link_id, linfo.remote_api, linfo.remote_ip
        self.task = None

    def run(self, t):
        self.task = t
        # get task info
        attr, args, kwargs_items = t.desc()
        # rebuild kwargs
        # (t did not returned a dict, this is would involve rpyc calls again)
        kwargs = { k:v for k, v in kwargs_items }
        # lookup task
        m = getattr(self, attr)
        # run task
        res = m(*args, **kwargs)
        # return result, unless async mode was set
        if not t.is_async():
            t.return_result(res)

    def register_session_object(self, obj):
        obj_id = len(self.session_objects)
        self.session_objects.append(obj)
        return obj_id

    def get_session_object(self, obj_id):
        return self.session_objects[obj_id]

    def on_connect(self):
        print 'session %d: connected' % self.link_id

    def on_disconnect(self):
        print 'session %d: disconnected' % self.link_id
        self.cleanup()
        del APISession.SESSIONS[self.link_id]

    def cleanup(self):
        for obj in self.session_objects:
            if hasattr(obj, 'cleanup'):
                obj.cleanup()

