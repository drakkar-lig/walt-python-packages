#!/usr/bin/env python
import re
from snimpy import manager

class SNMPBitField(object):
    def __init__(self, snmpfield, shift = 0):
        hex_string = snmpfield.encode('hex')
        self.bitlength = len(hex_string)*4
        self.value = int(hex_string, 16)
        self.shift = shift
    def __str__(self):
        format_string = '{:0%db}' % self.bitlength
        return format_string.format(self.value)
    def bit_index(self, index):
        return self.bitlength - index - 1 + self.shift
    def __getitem__(self, index):
        bitindex = self.bit_index(index)
        return (self.value & (1 << bitindex)) >> bitindex
    def __setitem__(self, index, val):
        currval = self[index]
        if val != currval:
            self.value ^= (1 << self.bit_index(index))
        # otherwise, nothing to do.
    def toOctetString(self):
        format_string = '{:0%dx}' % (self.bitlength / 4)
        return format_string.format(self.value).decode('hex')

# For ports-related bitfields, the indexing starts at 1
# because there is no port 0.
# e.g. port 1 status is the left-most bit
# So we use the 'shift = 1' constructor option. 
class PortsBitField(SNMPBitField):
    def __init__(self, snmpfield):
        SNMPBitField.__init__(self, snmpfield, shift = 1)

def load_mib(mib):
    if not mib in manager.loaded:
        manager.load(mib)

def unload_mib(mib):
    manager.loaded.remove(mib)

def get_loaded_mibs():
    return manager.loaded

def unload_any_of_these_mibs(mibs):
    for mib in mibs:
        if mib in manager.loaded:
            unload_mib(mib)

def decode_ipv4_address(octet_string):
    return '.'.join([str(ord(i)) for i in octet_string])

def decode_mac_address(octet_string):
    return ':'.join(re.findall('..', octet_string.encode('hex')))

def enum_label(enum):
    return enum.entity.enum[enum]

