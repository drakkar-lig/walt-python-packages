# coding=utf-8
import curses, os, cPickle as pickle
from walt.common.evloop import EventLoop
from walt.common.fifo import open_readable_fifo
from walt.server.const import UI_FIFO_PATH

class Console(object):
    def __init__(self):
        self.stdscr = curses.initscr()
        curses.curs_set(0) # invisible cursor
        max_y, max_x = self.stdscr.getmaxyx()
        self.stdscr.erase()
        self.stdscr.addstr('WalT server console', curses.A_BOLD | curses.A_UNDERLINE)
        self.status_win = self.stdscr.subwin(1, max_x, 2, 0)
        self.explain_win = self.stdscr.subwin(4, 0)
        self.BOX_DRAWING={
            u'┼': curses.ACS_PLUS,
            u'┌': curses.ACS_ULCORNER,
            u'─': curses.ACS_HLINE,
            u'│': curses.ACS_VLINE,
            u'┐': curses.ACS_URCORNER,
            u'┘': curses.ACS_LRCORNER,
            u'└': curses.ACS_LLCORNER
        }
        self.stdscr.refresh()
        self.fifo = open_readable_fifo(UI_FIFO_PATH)
    def __del__(self):
        curses.endwin()
        self.fifo.close()
        os.remove(UI_FIFO_PATH)
    def set_win_text(self, win, text, flags, erase):
        if erase:
            win.erase()
        for c in text:
            if c in self.BOX_DRAWING:
                c = self.BOX_DRAWING[c]
            else:
                c = str(c)
            try:
                win.addch(c, flags)
            except Exception:
                raise Exception('Issue with %s in %s' % (repr(c), repr(text)))
        win.refresh()
    def handle_request(self, req, *args):
        win = None
        if req == 'STATUS':
            win = self.status_win
            flags = curses.A_BOLD
            text = 'Status: ' + args[0].strip('\n')
            erase = True
        elif req == 'EXPLAIN':
            win = self.explain_win
            flags = 0
            text = args[0]
            erase = True
        elif req == 'TODO':
            win = self.explain_win
            flags = curses.A_BOLD
            text = args[0]
            erase = False
        elif req == 'WAIT_ENTER':
            response_fifo_path = args[0]
            # block until the user press a key
            self.stdscr.getch()
            # unblock the ui manager
            with open(response_fifo_path, 'w') as fifo:
                pickle.dump('done', fifo)
        else:
            raise Exception("Unexpected request!!! " + repr(req))
        if win is not None:
            self.set_win_text(win, text, flags, erase)
    def run(self):
        ev_loop = EventLoop()
        ev_loop.register_listener(self)
        ev_loop.loop()
    def fileno(self):
        return self.fifo.fileno()
    def handle_event(self, ts):
        args = pickle.load(self.fifo)
        self.handle_request(*args)

def run():
    console = Console()
    try:
        console.run()
    except KeyboardInterrupt:
        del console
    except Exception as e:
        del console
        raise e

