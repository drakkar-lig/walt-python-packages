import base64
import bz2
import os
import re
import sys
from itertools import zip_longest

from walt.common.term import TTYSettings

LOGO_DATA = bz2.decompress(base64.decodebytes(b"""
QlpoOTFBWSZTWckWUZ8ABrRreQAQAAh/6AAIAAJ/6MD+/4T575AAUANhg9wgYKGp6ICk9TeonqNN
MmnqABkep6gzyUw1PETSU0AAAAAAAAEmpCjQU2UDQeoaAZNDeqeU0DIYDQAADQAAAAABJpKpHpMQ
0yYEwjIxMEwTIaTAA0VxqW8+tVOsp/FGHcRVtGo70okIILCYoA9zEjSDlcJeCQI4PW8tsju2u2+s
MeFr2YG0xInkl74Yr1Z639E3yk3FNN72Mcd5U3SmooCxRyI8iUjco2HuZNHbLcOnS/LqQWJqyw5i
KmGgieZJZJdkcxfv8caOC507SIE3c+vhfrAzCfkJBzAhQEnZRx5CUWosWjVNBckuhGdsAhEDTBYR
4wdNGIWEFJBkFhcSMVKgcgYBCMmEFA1U1QUlNoE7ZddFyxaYRqltDAF6l6pYYkKgEJoERVV0urW5
QLBhVYsh5SQIaUAhEhDygEI6NSlNTV0aKgwFmi6JBBmpEl3kI2zU84QKMYwKlyYU5ZJzhYSys2FF
Xi8SWnJbl3q2IgYaYRvMBqWItUhJ3cmZGUYUBlGrCICFVJM2mVdsEJuKNUGyTRaTIMFXmJixO+AB
6EfgHfVCoXKAKGKMFlQhULlAhUkKwJFJC4ZEcLcckGsVpFWKoVgsTK2wcsCoSpG0MG+sIBC5mSEl
QACzGYwmkhcly0KyotHBcRVcSsyRVWDjZAUWGNcoWKGIBsH2OOwDzZOtDey7rPV50w6XQJKEJ2ZX
sKHew6L1Ie9MKydDA3ssxSYerXUM2HXto+VUSXQySLO5A3MswjO6GaZb6nFhmlkPBxqTQhxT8M2b
qCZIGxA/2VC7GGFVu/rVRz66ODN3m5rRZFkDazLvoPW5sNY8GhB20cza9SS7OTN+jbbF6AunQmCq
MP41IIgo+0tFAVFn/F3JFOFCQyRZRnw=""")).decode()
LOGO_WIDTH = 32

RE_SGR_ESC = re.compile(r"\x1b\[[^m]*m")

def try_add_logo(left_text):
    if not os.isatty(1):
        return left_text  # failed, cannot add logo
    tty = TTYSettings()
    # verify if terminal seems to handle 256 colors at least
    if tty.num_colors < 256:
        return left_text  # failed, cannot add logo
    # try to encode logo with terminal encoding
    try:
        logo_lines = LOGO_DATA.encode(sys.stdout.encoding).splitlines()
    except UnicodeEncodeError:
        return left_text  # failed, cannot add logo
    # verify terminal is large enough
    text_lines = left_text.splitlines()
    text_lengths = [len(RE_SGR_ESC.sub("", line)) for line in text_lines]
    max_text_len = max(text_lengths)
    if tty.cols < max_text_len + 3 + LOGO_WIDTH:
        return left_text  # failed, cannot add logo
    # ok, everything seems fine
    logo_lines = [l.decode(sys.stdout.encoding) for l in logo_lines]
    if len(logo_lines) > len(text_lines):
        text_lines = [""] * (len(logo_lines) - len(text_lines)) + text_lines
    out_text = ""
    for text_line, text_len, logo_line in zip_longest(
            text_lines, text_lengths, logo_lines):
        if text_line is None:
            text_line, text_len = "", 0
        if logo_line is None:
            logo_line = ""
        out_text += (text_line +
                     (max_text_len+3-text_len)*" " +
                     logo_line +
                     "\x1b[0m\n")
    return out_text
