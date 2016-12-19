import os, select, cPickle as pickle
from walt.server.const import UI_FIFO_PATH, UI_RESPONSE_FIFO_PATH
from walt.common.fifo import open_readable_fifo

class UIManager(object):
    def ui_running(self):
        return os.path.exists(UI_FIFO_PATH)
    def send_request_to_ui(self, *args):
        with open(UI_FIFO_PATH, 'w') as fifo:
            pickle.dump(args, fifo)
    def wait_user_keypress(self):
        if self.ui_running():
            response_fifo = open_readable_fifo(UI_RESPONSE_FIFO_PATH)
            self.send_request_to_ui('WAIT_ENTER', UI_RESPONSE_FIFO_PATH)
            # block until we get the response message back
            pickle.load(response_fifo)
            response_fifo.close()
            os.remove(UI_RESPONSE_FIFO_PATH)
        else:
            print "Press <enter> to continue...",
            raw_input()
    def request_ui_update(self, *args):
        if self.ui_running():
            self.send_request_to_ui(*args)
            return True
        else:
            return False
    def task_start(self, msg, explain=None, todo=None):
        self.task_idx = 0
        self.task_msg = msg
        self.task_explain = explain
        self.task_todo = todo
        self.task_explained_ui = False
        self.set_status(msg)
    def task_running(self, activity_sign=True):
        if self.task_explain and not self.task_explained_ui:
            self.task_explained_ui = self.set_explain(
                self.task_explain,
                self.task_todo,
                ui_only = True
            )
        if activity_sign:
            status_text = "%s %s" % \
                (self.task_msg, '|/-\\'[self.task_idx])
            self.task_idx = (self.task_idx + 1)%4
        else:
            status_text = self.task_msg
        self.set_status(status_text, ui_only=True)
    def task_done(self):
        status_text = "%s %s" % (self.task_msg, 'done')
        self.set_status(status_text)
        self.request_ui_update('EXPLAIN', '')
    def task_failed(self, error_msg):
        status_text = "%s %s" % (self.task_msg, 'FAILED!!')
        self.set_status(status_text)
        self.set_explain('ERROR:\n' + error_msg, None)
    def update_topic(self, topic, text, ui_only=False):
        if not ui_only:
            print '**', text
        return self.request_ui_update(topic, text)
    def set_status(self, *args, **kwargs):
        return self.update_topic('STATUS', *args, **kwargs)
    def set_explain(self, explain, todo, **kwargs):
        succeeded = self.update_topic('EXPLAIN', explain, **kwargs)
        if succeeded and todo is not None:
            succeeded = self.update_topic('TODO', todo, **kwargs)
        return succeeded
