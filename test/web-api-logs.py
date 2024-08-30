from includes.common import (
    define_test,
    test_create_vnode,
    get_vnode,
    test_json_request
)
from time import time, sleep


def test_log(json_log, t0, t1):
    assert len(json_log.keys()) == 4
    t = json_log.get("timestamp", 0)
    assert t >= t0 and t <= t1
    assert json_log.get("issuer", "") == "walt-server"
    assert json_log.get("stream", "") == "platform.nodes"


@define_test("web api/v1/logs?from=<t0>&to=<t1>")
def test_api_logs():
    # create a vnode, wait for bootup, check that we can retrieve the related
    # log line
    t0 = time()
    vnode = test_create_vnode()
    vnode.wait(); sleep(0.5)    # the server buffers logs a little
    t1 = time()
    dict_params = { "from": t0, "to": t1 }
    json_logs = test_json_request("logs", dict_params=dict_params)
    expected_logline = f"node {vnode.name} is booted"
    filtered = [ d for d in json_logs if d.get("line", "") == expected_logline ]
    assert len(filtered) == 1
    json_log = filtered[0]
    test_log(json_log, t0, t1)


@define_test("web api/v1/logs?from=<t0>&to=<t1>&<other-params>")
def test_api_logs_filter_issuer_stream():
    # we will specify ts_unit=ms, so multiply times by 1000
    t1 = time() *1000
    t0 = t1 - (3600*1000)   # 1 hour ago
    dict_params = {"from": t0,
                   "to": t1,
                   "ts_unit": "ms",
                   "issuer": "walt-server",
                   "stream": "platform.nodes"}
    json_logs = test_json_request("logs", dict_params=dict_params)
    assert len(json_logs) >= 1  # there should be 1 line of the prev test at least
    for json_log in json_logs:
        test_log(json_log, t0, t1)
    vnode = get_vnode()
    vnode.remove(force=True)  # last test of file, cleanup
