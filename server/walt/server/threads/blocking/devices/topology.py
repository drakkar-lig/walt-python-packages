from walt.server.tools import to_named_tuple

def rescan(requester, server, remote_ip, devices):
    # devices were transformed to dict to be pickle-able
    devices = [to_named_tuple(d) for d in devices]
    # rescan
    server.topology.rescan(requester=requester, remote_ip=remote_ip, devices=devices)
