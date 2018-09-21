#!/usr/bin/env python
import re

# values below match values of escape codes.
# https://misc.flogisoft.com/bash/tip_colors_and_formatting
UNDERLINE_ON = 4
UNDERLINE_OFF = 24
BOLD_ON = 1
BOLD_OFF = 21
DIM_ON = 2
DIM_OFF = 22

FG_COLOR_DEFAULT = 39
FG_COLOR_BLACK = 30
FG_COLOR_DARK_YELLOW = '38;5;172'
FG_COLOR_BLUE = 34
FG_COLOR_DARK_RED = '38;5;88'

BG_COLOR_DEFAULT = 49
BG_COLOR_WHITE = 107
BG_COLOR_LIGHT_GREY = 47

RE_ESC_COLOR = re.compile("\x1b\[[0-9;]*m")
