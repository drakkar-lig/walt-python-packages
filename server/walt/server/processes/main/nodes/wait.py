from collections import defaultdict

from walt.common.formatting import format_sentence_about_nodes

# note: sending a notification message to a requester or resuming a workflow
# may involve a remote procedure call, thus another bootup notification
# or wait request may be received at this time.
# as a result wait() and node_bootup_event() functions had to be
# carefully written regarding these remote procedure calls.


class WaitInfo(object):
    def __init__(self):
        self.wfid_to_macs = defaultdict(set)
        self.mac_to_wfids = defaultdict(set)
        self.mac_to_name = {}
        self.workflows = {}
        self.wfid_to_message = {}
        self.wfid_to_requester = {}
        self.completed_workflows = []

    def push_status_message(self, wfid):
        waiting_names = [self.mac_to_name[mac] for mac in self.wfid_to_macs[wfid]]
        message = format_sentence_about_nodes("Waiting for bootup of %s", waiting_names)
        self.wfid_to_message[wfid] = message

    def flush(self):
        wfid_to_message = self.wfid_to_message.copy()
        self.wfid_to_message = {}    # reset
        # resume workflows
        while len(self.completed_workflows) > 0:
            wf = self.completed_workflows[0]
            self.completed_workflows = self.completed_workflows[1:]
            wfid = id(wf)
            if wfid in wfid_to_message:
                del wfid_to_message[wfid]
            del self.wfid_to_requester[wfid]
            del self.workflows[wfid]
            del self.wfid_to_macs[wfid]
            wf.next()  # resume the workflow
        # send status messages
        for wfid, message in wfid_to_message.items():
            requester = self.wfid_to_requester[wfid]
            if not requester.get_username():
                continue  # requester is disconnected
            requester.set_busy_label(message)

    def wf_wait(self, wf, requester, nodes, **env):
        not_booted = [node for node in nodes if not node.booted]
        if len(not_booted) == 0:
            wf.next()
            return
        wfid = id(wf)
        self.workflows[wfid] = wf
        for node in not_booted:
            self.mac_to_wfids[node.mac].add(wfid)
            self.wfid_to_macs[wfid].add(node.mac)
            self.mac_to_name[node.mac] = node.name
        self.wfid_to_requester[wfid] = requester
        self.push_status_message(wfid)
        self.flush()

    def node_bootup_event(self, node):
        wfids = self.mac_to_wfids[node.mac]
        if len(wfids) > 0:
            del self.mac_to_wfids[node.mac]
            del self.mac_to_name[node.mac]
            for wfid in wfids:
                self.wfid_to_macs[wfid].remove(node.mac)
                if len(self.wfid_to_macs[wfid]) == 0:
                    # the queue is no more associated with any awaited nodes
                    self.completed_workflows.append(self.workflows[wfid])
                else:
                    # workflow is still waiting for other nodes, just let
                    # requester know that one more is booted
                    self.push_status_message(wfid)
            self.flush()
