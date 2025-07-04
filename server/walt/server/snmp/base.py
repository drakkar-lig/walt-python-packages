#!/usr/bin/env python
import functools
import re
from snimpy import snmp

from walt.server.diskcache import DISK_CACHE


class SNMPBitField(object):
    def __init__(self, snmpfield, shift=0):
        hex_string = snmpfield.encode("hex")
        self.bitlength = len(hex_string) * 4
        self.value = int(hex_string, 16)
        self.shift = shift

    def __str__(self):
        format_string = "{:0%db}" % self.bitlength
        return format_string.format(self.value)

    def bit_index(self, index):
        return self.bitlength - index - 1 + self.shift

    def __getitem__(self, index):
        bitindex = self.bit_index(index)
        return (self.value & (1 << bitindex)) >> bitindex

    def __setitem__(self, index, val):
        currval = self[index]
        if val != currval:
            self.value ^= 1 << self.bit_index(index)
        # otherwise, nothing to do.

    def toOctetString(self):
        format_string = "{:0%dx}" % (self.bitlength / 4)
        return format_string.format(self.value).decode("hex")


# For ports-related bitfields, the indexing starts at 1
# because there is no port 0.
# e.g. port 1 status is the left-most bit
# So we use the 'shift = 1' constructor option.
class PortsBitField(SNMPBitField):
    def __init__(self, snmpfield):
        SNMPBitField.__init__(self, snmpfield, shift=1)


def decode_ipv4_address(octet_string):
    return ".".join(str(i) for i in octet_string)


def decode_mac_address(value):
    if value.__class__.__name__ == "OctetString":
        return ":".join(re.findall("..", value.hex()))
    elif value.__class__.__name__ == "String":
        # input value may have high order zero chars ommitted,
        # e.g. 0:d:b9:45:f8:90, let's restore them
        return ":".join("%02x" % int(byte, base=16) for byte in value.split(":"))
    else:
        raise Exception(f"Could not decode {value} as a mac address")


def enum_label(enum):
    return enum.entity.enum[enum.real]


class NoSNMPVariantFound(Exception):
    pass


# In the worst case, on the WalT platform we
# could find devices of several vendors.
# In this case we usually have to unload a mib and load another one,
# and sometimes target a vendor-specific implementation
# each time we pass from one vendor to another.
# In order to handle this, we use classes implementing vendor-specific
# variants, and a wrapper around the SNMP proxy.

# In this file, we implement base classes. They are used in files
# lldp.py and poe.py.


class Variant:
    @classmethod
    def try_load(cls, snmp_proxy):
        cls.load()
        try:
            cls.test_or_exception(snmp_proxy)
            return True  # ok previous line passed with no error
        except (
            snmp.SNMPException,
            snmp.SNMPNoSuchObject,
            snmp.SNMPNoSuchInstance,
            snmp.SNMPEndOfMibView,
            ValueError,
        ):
            cls.unload()
            return False


class VariantsSet:
    def __init__(self, topic_msg, variants):
        self.topic_msg = topic_msg
        self.variants = variants
        self.loaded = None

    def load_auto(self, snmp_proxy, host):
        if self.loaded is not None:
            self.loaded.unload()
            self.loaded = None
        cache_key = ("snmp-variant", self.topic_msg, host)
        partial = functools.partial(self._probe_variant_name, snmp_proxy, host)
        variant_name = DISK_CACHE.get(cache_key, partial)
        for variant in self.variants:
            if variant.__name__ == variant_name:
                variant.load()
                self.loaded = variant
                return variant

    def _probe_variant_name(self, snmp_proxy, host):
        for variant in self.variants:
            if variant.try_load(snmp_proxy):
                return variant.__name__
        raise NoSNMPVariantFound(
            "Device %s does not seem to handle %s." % (host, self.topic_msg)
        )

    def ensure_variant(self, variant):
        if self.loaded is not variant:
            if self.loaded is not None:
                self.loaded.unload()
                self.loaded = None
            variant.load()
            self.loaded = variant


# The VariantProxy wrapper ensures that each time
# the SNMP proxy is accessed, the appropriate MIB is loaded, and
# variant-specific code is executed.


class VariantProxy(object):
    def __init__(self, snmp_proxy, host, variants):
        self.unsafe_proxy = snmp_proxy
        self.variants = variants
        self.selected_variant = variants.load_auto(snmp_proxy, host)

    @property
    def variant(self):
        self.variants.ensure_variant(self.selected_variant)
        return self.selected_variant

    @property
    def snmp(self):
        self.variants.ensure_variant(self.selected_variant)
        return self.unsafe_proxy
