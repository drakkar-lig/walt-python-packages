from collections import defaultdict

class WaitInfo(object):
    def __init__(self):
        self.tid_to_macs = defaultdict(set)
        self.mac_to_tids = defaultdict(set)
        self.tasks = {}

    def wait(self, requester, task, nodes):
        if nodes == None:
            return         # unblock the client
        not_booted = [ node for node in nodes if not node.booted ]
        if len(not_booted) == 0:
            return         # unblock the client
        # ok, the client will really have to wait
        task.set_async()   # result will be available later
        tid = id(task)
        self.tasks[tid] = task
        for node in not_booted:
            self.mac_to_tids[node.mac].add(tid)
            self.tid_to_macs[tid].add(node.mac)

    def node_bootup_event(self, node):
        print 'node bootup', node.name
        tids = self.mac_to_tids[node.mac]
        del self.mac_to_tids[node.mac]
        for tid in tids:
            self.tid_to_macs[tid].remove(node.mac)
            if len(self.tid_to_macs[tid]) == 0:
                # the queue is no more associated with any awaited nodes
                self.tasks[tid].return_result(0) # unblock the client
                del self.tasks[tid]
                del self.tid_to_macs[tid]
