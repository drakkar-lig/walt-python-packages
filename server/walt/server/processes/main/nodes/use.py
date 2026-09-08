
class ContinuousUseSession:
    def __init__(self, powersave_manager, nodes):
        self.powersave = powersave_manager
        self.nodes = nodes
        for node in self.nodes:
            print(f"record_start_use {node.mac}")
            self.powersave.record_start_use(node.mac)
    def cleanup(self):
        for node in self.nodes:
            print(f"record_end_use {node.mac}")
            self.powersave.record_end_use(node.mac)
