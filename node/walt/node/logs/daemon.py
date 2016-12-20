#!/usr/bin/env python
from walt.common.evloop import EventLoop
from walt.node.logs.listener import LogsFifoListener

def run():
    ev_loop = EventLoop()
    logs_fifo_listener = LogsFifoListener()
    logs_fifo_listener.join_event_loop(ev_loop)
    ev_loop.loop()

