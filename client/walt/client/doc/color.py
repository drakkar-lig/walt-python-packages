#!/usr/bin/env python
import re
from collections import namedtuple

FORMAT_ATTRS = ['bg_color', 'fg_color', 'underline', 'bold', 'dim']

# values below match values of escape codes.
# https://misc.flogisoft.com/bash/tip_colors_and_formatting
UNDERLINE_ON = '4'
UNDERLINE_OFF = '24'
BOLD_ON = '1'
DIM_ON = '2'
DIM_AND_BOLD_OFF = '22'

FG_COLOR_DEFAULT = '39'
FG_COLOR_BLACK = '30'
FG_COLOR_DARK_YELLOW = '38;5;172'
FG_COLOR_BLUE = '34'
FG_COLOR_DARK_RED = '38;5;88'

BG_COLOR_DEFAULT = '49'
BG_COLOR_WHITE = '107'
BG_COLOR_LIGHT_GREY = '47'

RE_ESC_COLOR = re.compile("\x1b\[[0-9;]*m")

class FormatState(namedtuple('FormatState', FORMAT_ATTRS)):
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
    if 'bold' in transitions and new_format.bold is False:
        codes.append(DIM_AND_BOLD_OFF)
        if new_format.dim is True:
            codes.append(DIM_ON)
    elif 'dim' in transitions and new_format.dim is False:
        codes.append(DIM_AND_BOLD_OFF)
        if new_format.bold is True:
            codes.append(BOLD_ON)
    else:
        if 'bold' in transitions:
            codes.append(BOLD_ON)   # since bold off is treated above
        if 'dim' in transitions:
            codes.append(DIM_ON)    # since dim off is treated above
    # underline is just a simple boolean
    if 'underline' in transitions:
        if new_format.underline is True:
            codes.append(UNDERLINE_ON)
        else:
            codes.append(UNDERLINE_OFF)
    # bg and fg colors are specified as color codes
    for attr in ('bg_color', 'fg_color'):
        if attr in transitions:
            codes.append(getattr(new_format, attr))
    # build the escape sequence
    if len(codes) == 0:
        return ''
    else:
        return '\x1b[' + ';'.join(codes) + 'm'
