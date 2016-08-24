from collections import defaultdict

class WaitInfo(object):
    def __init__(self):
        self.qid_to_macs = defaultdict(set)
        self.mac_to_qids = defaultdict(set)
        self.queues = {}

    def wait(self, requester, q, nodes):
        if nodes == None:
            q.put(0)    # unblock the client
        unreachable_nodes = [ node for node in nodes if node.reachable == 0 ]
        if len(unreachable_nodes) == 0:
            q.put(0)    # unblock the client
        # ok, the client will really have to wait
        qid = id(q)
        self.queues[qid] = q
        for node in unreachable_nodes:
            self.mac_to_qids[node.mac].add(qid)
            self.qid_to_macs[qid].add(node.mac)

    def node_bootup_event(self, node):
        print 'node bootup', node.name
        qids = self.mac_to_qids[node.mac]
        del self.mac_to_qids[node.mac]
        for qid in qids:
            self.qid_to_macs[qid].remove(node.mac)
            if len(self.qid_to_macs[qid]) == 0:
                # the queue is no more associated with any awaited nodes
                try:
                    self.queues[qid].put(0) # unblock the client
                except ReferenceError:
                    # the client already cancelled the wait
                    # thus the queue object no longer exists
                    # we can safely ignore that.
                    pass
                del self.queues[qid]
                del self.qid_to_macs[qid]
