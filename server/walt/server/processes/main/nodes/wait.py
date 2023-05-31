from collections import defaultdict

from walt.common.formatting import format_sentence_about_nodes

# note: sending a notification message to a requester or ending a task
# involves a remote procedure call, thus another bootup notification
# or wait request may be received at this time.
# as a result wait() and node_bootup_event() functions had to be
# carefully written regarding these remote procedure calls.


class WaitInfo(object):
    def __init__(self):
        self.tid_to_macs = defaultdict(set)
        self.mac_to_tids = defaultdict(set)
        self.mac_to_name = {}
        self.tasks = {}
        self.message_log = []
        self.completed_tasks = []

    def push_status_message(self, tid):
        requester = self.tasks[tid].context.requester
        waiting_names = [self.mac_to_name[mac] for mac in self.tid_to_macs[tid]]
        message = format_sentence_about_nodes("Waiting for bootup of %s", waiting_names)
        self.message_log.append((requester, message))

    def flush(self):
        # unblock clients
        while len(self.completed_tasks) > 0:
            task = self.completed_tasks[0]
            self.completed_tasks = self.completed_tasks[1:]
            task.return_result(0)  # unblock the client
        # send status messages
        while len(self.message_log) > 0:
            requester, message = self.message_log[0]
            self.message_log = self.message_log[1:]
            if not requester.get_username():
                continue  # requester is disconnected
            requester.set_busy_label(message)

    def wf_wait(self, wf, requester, task, nodes, **env):
        not_booted = [node for node in nodes if not node.booted]
        if len(not_booted) == 0:
            task.return_result(0)  # unblock the client
        tid = id(task)
        self.tasks[tid] = task
        for node in not_booted:
            self.mac_to_tids[node.mac].add(tid)
            self.tid_to_macs[tid].add(node.mac)
            self.mac_to_name[node.mac] = node.name
        self.push_status_message(tid)
        self.flush()

    def node_bootup_event(self, node):
        print("node bootup", node.name)
        tids = self.mac_to_tids[node.mac]
        if len(tids) > 0:
            del self.mac_to_tids[node.mac]
            del self.mac_to_name[node.mac]
            for tid in tids:
                self.tid_to_macs[tid].remove(node.mac)
                if len(self.tid_to_macs[tid]) == 0:
                    # the queue is no more associated with any awaited nodes
                    self.completed_tasks.append(self.tasks[tid])
                    del self.tasks[tid]
                    del self.tid_to_macs[tid]
                else:
                    # task is still waiting for other nodes, just let
                    # requester know that one more is booted
                    self.push_status_message(tid)
            self.flush()
