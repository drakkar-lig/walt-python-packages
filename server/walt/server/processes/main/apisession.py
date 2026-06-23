import itertools

from walt.common.tools import SimpleContainer
from walt.server.processes.main.task import APISessionTask


class APISession(object):
    SESSIONS = {}
    TARGET_APIS = {}
    SERVER_CONTEXT = None
    SESSION_OBJECTS = {}
    SESSION_IDS_GENERATOR = itertools.count()

    @staticmethod
    def register_target_api(name, cls):
        APISession.TARGET_APIS[name] = cls

    @staticmethod
    def create(server, session_id, target_api, remote_ip):
        cls = APISession.TARGET_APIS[target_api]
        APISession.SESSIONS[session_id] = cls(server, remote_ip)
        # print("session %d: connected" % session_id)

    @staticmethod
    def destroy(session_id):
        # print("session %d: disconnected" % session_id)
        APISession.SESSIONS[session_id].cleanup()
        del APISession.SESSIONS[session_id]

    @staticmethod
    def cleanup_all():
        for session in APISession.SESSIONS.values():
            session.cleanup()

    @staticmethod
    def get(server, session_id, target_api, remote_ip):
        if session_id not in APISession.SESSIONS:
            APISession.create(server, session_id, target_api, remote_ip)
        return APISession.SESSIONS[session_id]

    def __init__(self, server, remote_ip):
        self._my_session_object_ids = []
        if APISession.SERVER_CONTEXT is None:
            APISession.SERVER_CONTEXT = SimpleContainer(
                server=server,
                images=server.images,
                devices=server.devices,
                blocking=server.blocking,
                nodes=server.nodes,
                logs=server.logs,
            )
        self.context = APISession.SERVER_CONTEXT.copy().update(
            remote_ip=remote_ip,
        )
        self._cached_username = (False,)

    def run_task(self, rpc_context, attr, args, kwargs):
        task = APISessionTask(rpc_context, self, attr, args, kwargs)
        return task.run()

    def get_username(self, rpc_context):
        if not self._cached_username[0]:
            username = rpc_context.remote_service.do_sync.requester.get_username()
            self._cached_username = (True, username)
        return self._cached_username[1]

    def register_session_object(self, obj):
        # note: session objects might be registered by an API
        # and retrieved by another one
        # (e.g., CSAPI and SSAPI for image build runtime)
        obj_id = next(self.SESSION_IDS_GENERATOR)
        self.SESSION_OBJECTS[obj_id] = obj
        self._my_session_object_ids.append(obj_id)
        return obj_id

    def get_session_object(self, obj_id):
        return self.SESSION_OBJECTS[obj_id]

    def cleanup(self):
        for obj_id in self._my_session_object_ids:
            obj = self.SESSION_OBJECTS.pop(obj_id)
            if hasattr(obj, "cleanup"):
                obj.cleanup()
