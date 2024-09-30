from includes.common import define_test, test_create_vnode
from walt.client import api


@define_test("api logs.get_logs()")
def test_api_logs_get_logs():
    node = test_create_vnode()
    # note: some other testing is done in walt-log.sh
    for logline in api.logs.get_logs(
        history="-10s:", realtime=True, issuers="server", timeout=60
    ):
        assert hasattr(logline, "timestamp")
        assert hasattr(logline, "line")
        assert hasattr(logline, "issuer")
        assert hasattr(logline, "stream")
        assert logline.issuer.device_type == "server"
        if logline.line == f"node {node.name} is booted":
            break
    assert node.booted
    # check the timeout feature
    # note: the node will probably send a few more log lines because of the netconsole,
    # the timeout will be raised only when it gets idle
    from time import time

    from walt.client.timeout import TimeoutException

    t0 = time()
    while True:
        try:
            for logline in api.logs.get_logs(realtime=True, issuers=node, timeout=1):
                assert (
                    time() - t0 < 30
                ), f"{node.name} still sending logs long after boot: {logline.line}"
                break  # exit the for loop, continue the while loop
        except TimeoutException:
            break  # ok, it was expected
    # check other forms for 'issuers'
    api.logs.get_logs(history="-10s:", issuers="my-nodes")
    api.logs.get_logs(history="-2m:-1m", issuers="all-nodes")
    api.logs.get_logs(history="-1d:", issuers="my-nodes,server")
    api.logs.get_logs(history="-10s:", issuers=(node.name, "server"))
    api.logs.get_logs(history="-10s:", issuers=(node.name, "server"))
    api.logs.get_logs(history="-10s:", issuers=node)
    api.logs.get_logs(history="-10s:", issuers=api.nodes.get_nodes())
    # cleanup
    node.remove(force=True)
