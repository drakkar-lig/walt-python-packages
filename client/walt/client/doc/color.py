#!/usr/bin/env python
import itertools
import re
from collections import namedtuple

FORMAT_ATTRS = ["bg_color", "fg_color", "underline", "bold", "dim"]

# values below match values of escape codes.
# https://misc.flogisoft.com/bash/tip_colors_and_formatting
UNDERLINE_ON = "4"
UNDERLINE_OFF = "24"
BOLD_ON = "1"
DIM_ON = "2"
DIM_AND_BOLD_OFF = "22"

C256_BLACK = 0
C256_BLUE = 4
C256_LIGHT_GREY = 7
C256_WHITE = 15
C256_DARK_YELLOW = 172
C256_DARK_RED = 88


# note: we could use only "[34]8;5;{c}" codes, but for a smaller
# formatted text we prefer to generate short codes for standard colors
def C256_FG(c):
    return f"38;5;{c}" if c > 15 else f"{82+c}" if c > 7 else f"{30+c}"


def C256_BG(c):
    return f"48;5;{c}" if c > 15 else f"{92+c}" if c > 7 else f"{40+c}"


FG_COLOR_DEFAULT = "39"
FG_COLOR_BLACK = C256_FG(C256_BLACK)
FG_COLOR_DARK_YELLOW = C256_FG(C256_DARK_YELLOW)
FG_COLOR_BLUE = C256_FG(C256_BLUE)
FG_COLOR_DARK_RED = C256_FG(C256_DARK_RED)

BG_COLOR_DEFAULT = "49"
BG_COLOR_WHITE = C256_BG(C256_WHITE)
BG_COLOR_LIGHT_GREY = C256_BG(C256_LIGHT_GREY)

RE_ESC_COLOR = re.compile("\x1b" + r"\[[0-9;]*m")
RE_SPACES = re.compile(r"^\s+$", re.ASCII)


class FormatState(namedtuple("FormatState", FORMAT_ATTRS)):
    def alter(self, **kwargs):
        state = dict(**self._asdict())
        state.update(**kwargs)
        return FormatState(**state)


def get_transition_esc_sequence(old_format, new_format):
    transitions = set()
    codes = []
    # start by checking what changed
    for name in FORMAT_ATTRS:
        if getattr(new_format, name) != getattr(old_format, name):
            transitions.add(name)
    # bold and dim have to be carefully processed because of the
    # lack of a portable way to disable one of them individually
    if "bold" in transitions and new_format.bold is False:
        codes.append(DIM_AND_BOLD_OFF)
        if new_format.dim is True:
            codes.append(DIM_ON)
    elif "dim" in transitions and new_format.dim is False:
        codes.append(DIM_AND_BOLD_OFF)
        if new_format.bold is True:
            codes.append(BOLD_ON)
    else:
        if "bold" in transitions:
            codes.append(BOLD_ON)  # since bold off is treated above
        if "dim" in transitions:
            codes.append(DIM_ON)  # since dim off is treated above
    # underline is just a simple boolean
    if "underline" in transitions:
        if new_format.underline is True:
            codes.append(UNDERLINE_ON)
        else:
            codes.append(UNDERLINE_OFF)
    # bg and fg colors are specified as color codes
    for attr in ("bg_color", "fg_color"):
        if attr in transitions:
            codes.append(getattr(new_format, attr))
    # build the escape sequence
    if len(codes) == 0:
        return ""
    else:
        return "\x1b[" + ";".join(codes) + "m"


def optimize_and_reset_default_colors(s, default_fg, default_bg):
    default_fg = str(default_fg)
    default_bg = str(default_bg)
    # ensure that at the end the specified color defaults are set
    # and dim/bold/italic/underline are unset
    s = s + f"\x1b[{default_fg};{default_bg};22;23;24m"
    s2 = ""
    start = 0
    end = 0
    bg, fg, bold, dim, italic, underline = (
            BG_COLOR_DEFAULT, FG_COLOR_DEFAULT, False, False, False, False)
    target_bg, target_fg, target_bold, target_dim, target_italic, target_underline = (
            default_bg, default_fg, False, False, False, False)
    # We use itertools.chain to append a None at the end of the
    # iteration. We will use it to detect the end and flush
    # remaining escape codes.
    for m in itertools.chain(RE_ESC_COLOR.finditer(s), (None,)):
        # considering the chars we have to print between two
        # ascii escape sequences (e.g., only spaces), we can differ
        # the emission of some escape codes (e.g., foreground color
        # or bold activation, in case of spaces). If on a next
        # escape sequence the same property is changed again,
        # these differed escape codes are actually optimized out
        # from the output string.
        if m is None:
            # end marker, flush remaining codes
            pending_chars = s[end:]
            update_foreground, update_background = True, True
        else:
            start = m.start()
            pending_chars = s[end:start]
            if len(pending_chars) == 0:
                # no pending chars, we can differ the output of
                # escape codes
                update_foreground, update_background = False, False
            elif RE_SPACES.match(pending_chars):
                # only spaces, we can differ the update of
                # escape codes related to the foreground
                update_foreground, update_background = False, True
            else:
                # other kinds of pending chars, update all
                update_foreground, update_background = True, True
        # prepare and emit the escape sequence if needed
        diff_codes = []
        if update_background and target_bg != bg:
            diff_codes.append(target_bg)
            bg = target_bg
        if update_foreground and target_fg != fg:
            diff_codes.append(target_fg)
            fg = target_fg
        if update_foreground and target_italic != italic:
            diff_codes.append("3" if target_italic else "23")
            italic = target_italic
        if update_foreground and target_underline != underline:
            diff_codes.append("4" if target_underline else "24")
            underline = target_underline
        if update_foreground and (target_bold, target_dim) != (bold, dim):
            if (
                    (bold, target_bold) == (True, False) or
                    (dim, target_dim) == (True, False)
               ):
                # we have to turn off at least one of bold or dim
                # we use code 22 (most compatible), which turns both off
                diff_codes.append("22")
                # update for the two next tests below
                bold, dim = False, False
            if not bold and target_bold:
                diff_codes.append("1")
            if not dim and target_dim:
                diff_codes.append("2")
            bold, dim = target_bold, target_dim
        if len(diff_codes) > 0:
            s2 += "\x1b[" + ";".join(diff_codes) + "m"
        # emit pending chars
        s2 += pending_chars
        if m is not None:  # if not the end marker
            # analyse current escape sequence
            codes = tuple(m.group()[2:-1].split(";"))
            while len(codes) > 0:
                c = int(codes[0])
                if c == 38 or c == 48:
                    # 38;5;<n> (fg color) or 48;5;<n> (bg color)
                    assert int(codes[1]) == 5
                    if c == 38:
                        target_fg = ";".join(codes[:3])
                    else:  # c == 48
                        target_bg = ";".join(codes[:3])
                    codes = codes[3:]
                else:
                    if c == 0:  # reset all
                        target_bg = default_bg
                        target_fg = default_fg
                        target_bold, target_dim, target_italic, target_underline = (
                                False, False, False, False)
                    elif (c >= 30 and c <= 37) or (c >= 90 and c <= 97):
                        target_fg = codes[0]
                    elif (c >= 40 and c <= 47) or (c >= 100 and c <= 107):
                        target_bg = codes[0]
                    elif c == 39:
                        target_fg = default_fg
                    elif c == 49:
                        target_bg = default_bg
                    elif c == 1:
                        target_bold = True
                    elif c == 2:
                        target_dim = True
                    elif c == 22:   # dim and bold off
                        target_bold = False
                        target_dim = False
                    elif c == 3:
                        target_italic = True
                    elif c == 23:
                        target_italic = False
                    elif c == 4:
                        target_underline = True
                    elif c == 24:
                        target_underline = False
                    else:
                        raise Exception(f"Unexpected ascii escape code {c}")
                    # all these codes are encoded as a single integer
                    codes = codes[1:]
            end = m.end()
    return s2
