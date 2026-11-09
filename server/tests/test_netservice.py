"""Unit tests of the node bootup status management (netservice.py).

These tests drive NodeNetServiceManager through the same entry points
as the real server:
- a node connecting (NodeNetServiceListener creation),
- a lost connection (NodeNetServiceListener.handle_event()),
- explicit up/down requests (change_nodes_bootup_status()),
- the event loop calling _bg_process(),
and replace the database, logs, event loop and the other managers
by small fakes recording what they receive.
"""
import numpy as np
import pytest

from walt.server.processes.main.nodes import netservice as ns

T0 = 1_000_000.0
NODES = {
    # name: (ip, mac)
    "vn1": ("192.168.152.1", "52:54:00:00:00:01"),
    "vn2": ("192.168.152.2", "52:54:00:00:00:02"),
    "rpi": ("192.168.152.3", "b8:27:eb:00:00:03"),
}
DEFAULT_RETRIES = ns.NODE_DEFAULT_BOOT_RETRIES
DEFAULT_TIMEOUT = ns.NODE_DEFAULT_BOOT_TIMEOUT


def object_recarray(rows, names):
    # the database returns recarrays with 'object' columns
    dt = np.dtype([(name, object) for name in names])
    return np.array([tuple(row) for row in rows], dt).view(np.recarray)


class Node:
    def __init__(self, name):
        self.name = name
        self.ip, self.mac = NODES[name]


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now

    def advance(self, delay):
        self.now += delay


class FakeDB:
    """Implements the query of _fetch_booted_events(): join events
       with the devices table, and drop events of unknown ips."""
    def __init__(self):
        self.devices = {ip: (name, mac) for name, (ip, mac) in NODES.items()}

    def execute(self, sql, args):
        assert "LEFT JOIN devices d ON e.ip = d.ip" in sql
        names = ("name", "mac", "ip", "event_ts", "conn_serial", "booted",
                 "cause", "ll_details", "logline", "priority")
        rows = [self.devices[ip] + (ip, ts, serial, booted, cause, details,
                                    None, 0)
                for ip, ts, serial, booted, cause, details in args
                if ip in self.devices]
        return object_recarray(rows, names)


class FakeLogs:
    def __init__(self):
        self.lines = []

    def platform_log(self, stream, line=None, lines=None, error=False):
        assert stream == "nodes"
        self.lines += [line] if lines is None else list(lines)


class FakeDevices:
    def get_multiple_device_info(self, where_sql, args):
        macs = args[0]
        by_mac = {mac: (name, ip) for name, (ip, mac) in NODES.items()}
        return object_recarray(
            [(mac,) + by_mac[mac] for mac in macs], ("mac", "name", "ip"))


class FakeEvLoop:
    def __init__(self):
        self.planned = []

    def plan_event(self, ts, callback):
        self.planned.append(ts)


class BootupEventsRecorder:
    def __init__(self):
        self.macs = []

    def node_bootup_event(self, node_info):
        self.macs.append(node_info.mac)


class FakeNodesManager:
    def __init__(self):
        self.ev_loop = FakeEvLoop()
        self.db = FakeDB()
        self.logs = FakeLogs()
        self.devices = FakeDevices()
        self.wait_info = BootupEventsRecorder()
        self.powersave = BootupEventsRecorder()
        self.reboots = []
        self.netservice = None

    def reboot_nodes(self, requester, cb, nodes, hard_only, cause,
                     reset_boot_retries=True):
        # behave like reboot.py for virtual nodes
        self.reboots.append((tuple(nodes.name), cause, reset_boot_retries))
        if reset_boot_retries:
            self.netservice.reset_boot_retries(nodes)
        self.netservice.change_nodes_bootup_status(
                nodes, booted=False, cause=cause, method="vnode hard-reboot")
        cb("OK")


class FakeSockFile:
    def __init__(self, ip):
        self.ip = ip
        self.closed = False
        self.written = []

    def getpeername(self):
        return (self.ip, 12345)

    def write(self, data):
        self.written.append(data)

    def set_keepalive(self):
        pass

    def readline(self):
        return b""  # the connection was lost

    def fileno(self):
        return 42

    def close(self):
        self.closed = True


class Platform:
    """The netservice manager, its fake environment, and helpers."""

    def __init__(self, clock):
        self.clock = clock
        self.nodes_manager = FakeNodesManager()
        self.mgr = ns.NodeNetServiceManager(FakeTCPServer(),
                                            self.nodes_manager)
        self.nodes_manager.netservice = self.mgr
        self.sock_files_per_ip = {}
        self.listeners_per_ip = {}
        rows = [(mac, DEFAULT_TIMEOUT, DEFAULT_RETRIES, DEFAULT_RETRIES,
                 "startup", T0, None) for ip, mac in NODES.values()]
        self.mgr._record_boot_info(object_recarray(rows, (
            "mac", "timeout", "retries", "remaining_retries", "cause",
            "boot_start_time", "netservice")))

    # events
    def connect(self, name):
        """The node opens its net-service connection (i.e., it booted)."""
        return ns.NodeNetServiceListener(
                self.mgr, FakeSockFile(NODES[name][0]),
                self.sock_files_per_ip, self.listeners_per_ip)

    def disconnect(self, listener, detection_ts=None):
        """The event loop detects the loss of a connection."""
        if detection_ts is None:
            detection_ts = self.clock()
        assert listener.handle_event(detection_ts) is False

    def down(self, *names, **details):
        self.mgr.change_nodes_bootup_status(
                [Node(name) for name in names], booted=False, **details)

    def batch(self):
        """Events queued in this context are processed as a single batch
           when it exits, as happens when they occur while a previous
           batch (e.g., a reboot) is still being processed."""
        return Batch(self.mgr)

    def fire_boot_timeouts(self):
        """Wait for the boot timeout and let the event loop run the
           planned boot check."""
        self.clock.advance(DEFAULT_TIMEOUT)
        self.mgr._bg_process()

    # observations
    @property
    def booted(self):
        return {name for name, (ip, mac) in NODES.items()
                if mac in self.mgr.get_booted_macs()}

    @property
    def logs(self):
        return self.nodes_manager.logs.lines

    def boot_info(self, name):
        table = self.mgr._boot_info_table
        return table[table.mac == NODES[name][1]][0]

    def remaining_retries(self, name):
        return self.boot_info(name).remaining_retries

    def mac(self, name):
        return NODES[name][1]


class FakeTCPServer:
    def register_listener_class(self, **kwargs):
        pass


class Batch:
    def __init__(self, mgr):
        self.mgr = mgr

    def __enter__(self):
        self.mgr._bg_processing = True

    def __exit__(self, *exc):
        self.mgr._bg_processing = False
        self.mgr._bg_process()


@pytest.fixture
def clock(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(ns, "time", clock)
    return clock


@pytest.fixture
def platform(clock):
    return Platform(clock)


# -- basic transitions -----------------------------------------------------

def test_connection_means_booted(platform):
    platform.connect("vn1")
    assert platform.booted == {"vn1"}
    assert platform.logs == ["node vn1 is booted"]
    assert platform.nodes_manager.wait_info.macs == [platform.mac("vn1")]
    assert platform.nodes_manager.powersave.macs == [platform.mac("vn1")]


def test_lost_connection_means_down(platform, clock):
    listener = platform.connect("vn1")
    clock.advance(10)
    platform.disconnect(listener)
    assert platform.booted == set()
    assert platform.logs[-1] == ("node vn1 is down (cause: unknown "
                                 "(empty read), note: server-detected "
                                 "disconnection)")
    info = platform.boot_info("vn1")
    assert info.cause == "unknown (empty read)"
    assert info.boot_start_time == clock()


def test_explicit_down_records_cause(platform, clock):
    platform.connect("vn1")
    clock.advance(10)
    platform.down("vn1", cause="powersave", method="PoE")
    assert platform.booted == set()
    assert platform.logs[-1] == "node vn1 is down (cause: powersave, method: PoE)"
    assert platform.boot_info("vn1").cause == "powersave"


def test_event_of_unknown_ip_is_ignored(platform):
    # e.g., a virtual node which was just removed
    del platform.nodes_manager.db.devices[NODES["vn2"][0]]
    with platform.batch():
        platform.connect("vn1")
        platform.connect("vn2")
    assert platform.booted == {"vn1"}
    assert platform.logs == ["node vn1 is booted"]


def test_redundant_booted_event_is_logged_but_not_notified(platform, clock):
    platform.connect("vn1")
    clock.advance(10)
    platform.connect("vn1")     # reconnection, old one not detected lost yet
    assert platform.booted == {"vn1"}
    assert platform.logs == ["node vn1 is booted"] * 2
    assert platform.nodes_manager.wait_info.macs == [platform.mac("vn1")]


# -- event ordering ----------------------------------------------------------

def test_down_then_reconnection_in_same_batch(platform, clock):
    # Regression test: the 'booted' event used the connection serial number
    # as its timestamp, so it was always processed before the 'down' event,
    # and the node was considered down although it had rebooted.
    platform.connect("vn1")
    clock.advance(10)
    with platform.batch():
        platform.down("vn1", cause="image change", method="soft-reboot")
        clock.advance(5)
        platform.connect("vn1")
    assert platform.booted == {"vn1"}
    assert platform.logs[-2:] == [
        "node vn1 is down (cause: image change, method: soft-reboot)",
        "node vn1 is booted",
    ]


def test_events_queued_out_of_order_are_sorted(platform, clock):
    # Because of event loop reentrancy, the detection of a lost connection
    # may be queued after an event which actually occured later.
    listener = platform.connect("vn1")
    clock.advance(10)
    detection_ts = clock()
    with platform.batch():
        clock.advance(1)
        new_listener = platform.connect("vn1")
        platform.disconnect(listener, detection_ts=detection_ts)
    assert platform.booted == {"vn1"}
    assert platform.logs[-2].startswith("node vn1 is down (cause: unknown")
    assert platform.logs[-1] == "node vn1 is booted"
    assert new_listener.conn_serial > listener.conn_serial


def test_disconnection_of_obsolete_connection_is_ignored(platform, clock):
    # The node rebooted and reconnected before the loss of its previous
    # connection was detected.
    old_listener = platform.connect("vn1")
    clock.advance(10)
    platform.connect("vn1")
    clock.advance(10)
    platform.disconnect(old_listener)
    assert platform.booted == {"vn1"}
    assert platform.logs == ["node vn1 is booted"] * 2


def test_disconnection_after_explicit_down_is_ignored(platform, clock):
    # The connection is lost as a consequence of a reboot request.
    listener = platform.connect("vn1")
    clock.advance(10)
    platform.down("vn1", cause="user request", method="soft-reboot")
    clock.advance(1)
    platform.disconnect(listener)
    assert platform.booted == set()
    assert platform.logs == [
        "node vn1 is booted",
        "node vn1 is down (cause: user request, method: soft-reboot)",
    ]
    assert platform.boot_info("vn1").cause == "user request"


def test_several_events_per_node_in_one_batch(platform, clock):
    listener1 = platform.connect("vn1")
    clock.advance(10)
    with platform.batch():
        platform.down("vn1", cause="user request", method="soft-reboot")
        clock.advance(1)
        platform.connect("vn2")
        clock.advance(1)
        platform.disconnect(listener1)   # ignored, vn1 already down
        clock.advance(1)
        listener2 = platform.connect("vn1")
        clock.advance(1)
        platform.disconnect(listener2)
        clock.advance(1)
        platform.connect("rpi")
    assert platform.booted == {"vn2", "rpi"}
    # events of distinct nodes may be grouped, but the timeline of each
    # node is respected.
    vn1_logs = [line for line in platform.logs if "vn1" in line]
    assert vn1_logs == [
        "node vn1 is booted",
        "node vn1 is down (cause: user request, method: soft-reboot)",
        "node vn1 is booted",
        "node vn1 is down (cause: unknown (empty read), "
        "note: server-detected disconnection)",
    ]
    assert sorted(platform.nodes_manager.wait_info.macs) == sorted(
            [platform.mac("vn1")] * 2 + [platform.mac("vn2"),
                                         platform.mac("rpi")])


def test_different_causes_in_one_batch(platform, clock):
    platform.connect("vn1")
    platform.connect("vn2")
    clock.advance(10)
    with platform.batch():
        platform.down("vn1", cause="powersave", method="PoE")
        platform.down("vn2", cause="user request", method="soft-reboot")
    assert platform.boot_info("vn1").cause == "powersave"
    assert platform.boot_info("vn2").cause == "user request"


# -- boot timeouts and retries ---------------------------------------------

def test_boot_timeout_retries_decrease(platform):
    # Regression test: the 'down' event caused by the hard-reboot used to
    # reset the number of retries, so it stayed at 'retries - 1'.
    platform.connect("vn2")
    platform.connect("rpi")
    expected = []
    for i in range(1, 4):
        platform.fire_boot_timeouts()
        assert platform.remaining_retries("vn1") == DEFAULT_RETRIES - i
        expected.append("vn1: boot timeout reached, trying hard-reboot "
                        f"({DEFAULT_RETRIES - i} retries left).")
    assert [line for line in platform.logs if "timeout reached" in line] \
            == expected
    assert platform.nodes_manager.reboots == [
            (("vn1",), "bootup timeout", False)] * 3


def test_boot_timeout_last_try(platform):
    platform.connect("vn2")
    platform.connect("rpi")
    for i in range(DEFAULT_RETRIES):
        platform.fire_boot_timeouts()
    assert platform.remaining_retries("vn1") == 0
    assert platform.logs[-2] == ("vn1: boot timeout reached, "
                                 "trying hard-reboot (last try).")
    # no more reboots after the last try
    platform.fire_boot_timeouts()
    assert len(platform.nodes_manager.reboots) == DEFAULT_RETRIES


def test_booted_node_going_down_resets_retries(platform, clock):
    platform.connect("vn2")
    platform.connect("rpi")
    platform.fire_boot_timeouts()
    platform.fire_boot_timeouts()
    assert platform.remaining_retries("vn1") == DEFAULT_RETRIES - 2
    listener = platform.connect("vn1")
    clock.advance(10)
    platform.disconnect(listener)
    assert platform.remaining_retries("vn1") == DEFAULT_RETRIES


def test_booted_nodes_are_not_rebooted(platform):
    for name in NODES:
        platform.connect(name)
    platform.fire_boot_timeouts()
    assert platform.nodes_manager.reboots == []


def test_powersave_nodes_are_not_rebooted(platform, clock):
    for name in NODES:
        platform.connect(name)
    clock.advance(10)
    platform.down("rpi", cause="powersave", method="PoE")
    platform.fire_boot_timeouts()
    assert platform.nodes_manager.reboots == []


def test_lost_node_is_rebooted_after_timeout(platform, clock):
    for name in NODES:
        platform.connect(name)
    clock.advance(10)
    lost_ts = clock()
    platform.disconnect(platform.listeners_per_ip[NODES["rpi"][0]])
    assert platform.boot_info("rpi").boot_start_time == lost_ts
    platform.fire_boot_timeouts()
    assert platform.nodes_manager.reboots == [
            (("rpi",), "bootup timeout", False)]
    assert platform.remaining_retries("rpi") == DEFAULT_RETRIES - 1
