import base64
import bz2
import os
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
    max_text_len = max(len(line) for line in text_lines)
    if tty.cols < max_text_len + 3 + LOGO_WIDTH:
        return left_text  # failed, cannot add logo
    # ok, everything seems fine
    if len(logo_lines) > len(text_lines):
        text_lines = [""] * (len(logo_lines) - len(text_lines)) + text_lines
    format_string = "%-" + str(max_text_len) + "s   %s\x1b[0m\n"
    out_text = ""
    for text_line, logo_line in zip_longest(text_lines, logo_lines, fillvalue=""):
        out_text += format_string % (text_line, logo_line.decode(sys.stdout.encoding))
    return out_text
