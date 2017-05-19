from walt.common.tools import SimpleContainer
from walt.server.threads.main.task import APISessionTask

class APISession(object):

    NEXT_ID = 0
    SESSIONS = {}
    TARGET_APIS = {}
    SERVER_CONTEXT = None

    @staticmethod
    def register_target_api(name, cls):
        APISession.TARGET_APIS[name] = cls

    @staticmethod
    def create(server, target_api, remote_ip):
        session_id = APISession.NEXT_ID
        APISession.NEXT_ID += 1
        cls = APISession.TARGET_APIS[target_api]
        APISession.SESSIONS[session_id] = cls(server, remote_ip)
        print 'session %d: connected' % session_id
        return session_id

    @staticmethod
    def destroy(session_id):
        print 'session %d: disconnected' % session_id
        APISession.SESSIONS[session_id].cleanup()
        del APISession.SESSIONS[session_id]

    @staticmethod
    def cleanup_all():
        for session in APISession.SESSIONS.values():
            session.cleanup()

    @staticmethod
    def get(session_id):
        return APISession.SESSIONS[session_id]

    def __init__(self, server, remote_ip):
        self.session_objects = []
        if APISession.SERVER_CONTEXT == None:
            APISession.SERVER_CONTEXT = SimpleContainer(
                    server = server,
                    images = server.images,
                    devices = server.devices,
                    topology = server.topology,
                    nodes = server.nodes,
                    logs = server.logs
            )
        self.context = APISession.SERVER_CONTEXT.copy().update(
            remote_ip = remote_ip,
        )

    def run_task(self, rpc_context, attr, args, kwargs):
        task = APISessionTask(rpc_context, self, attr, args, kwargs)
        task.run()

    def register_session_object(self, obj):
        obj_id = len(self.session_objects)
        self.session_objects.append(obj)
        return obj_id

    def get_session_object(self, obj_id):
        return self.session_objects[obj_id]

    def cleanup(self):
        for obj in self.session_objects:
            if hasattr(obj, 'cleanup'):
                obj.cleanup()

