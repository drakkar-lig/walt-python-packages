#!/usr/bin/env python
import random

class DiffieHellman(object):
    BITSIZE = 2048

    # RFC 5114 section 2.3
    p = int(''.join("""
    87A8E61D B4B6663C FFBBD19C 65195999 8CEEF608 660DD0F2
    5D2CEED4 435E3B00 E00DF8F1 D61957D4 FAF7DF45 61B2AA30
    16C3D911 34096FAA 3BF4296D 830E9A7C 209E0C64 97517ABD
    5A8A9D30 6BCF67ED 91F9E672 5B4758C0 22E0B1EF 4275BF7B
    6C5BFC11 D45F9088 B941F54E B1E59BB8 BC39A0BF 12307F5C
    4FDB70C5 81B23F76 B63ACAE1 CAA6B790 2D525267 35488A0E
    F13C6D9A 51BFA4AB 3AD83477 96524D8E F6A167B5 A41825D9
    67E144E5 14056425 1CCACB83 E6B486F6 B3CA3F79 71506026
    C0B857F6 89962856 DED4010A BD0BE621 C3A3960A 54E710C3
    75F26375 D7014103 A4B54330 C198AF12 6116D227 6E11715F
    693877FA D7EF09CA DB094AE9 1E1A1597
    """.split()), 16)

    g = int(''.join("""
    3FB32C9B 73134D0B 2E775066 60EDBD48 4CA7B18F 21EF2054
    07F4793A 1A0BA125 10DBC150 77BE463F FF4FED4A AC0BB555
    BE3A6C1B 0C6B47B1 BC3773BF 7E8C6F62 901228F8 C28CBB18
    A55AE313 41000A65 0196F931 C77A57F2 DDF463E5 E9EC144B
    777DE62A AAB8A862 8AC376D2 82D6ED38 64E67982 428EBC83
    1D14348F 6F2F9193 B5045AF2 767164E1 DFC967C1 FB3F2E55
    A4BD1BFF E83B9C80 D052B985 D182EA0A DB2A3B73 13D3FE14
    C8484B1E 052588B9 B7D2BBD2 DF016199 ECD06E15 57CD0915
    B3353BBB 64E0EC37 7FD02837 0DF92B52 C7891428 CDC67EB6
    184B523D 1DB246C3 2F630784 90F00EF8 D647D148 D4795451
    5E2327CF EF98C582 664B4C0F 6CC41659
    """.split()), 16)

    @staticmethod
    def generate_priv_key():
        return random.getrandbits(DiffieHellman.BITSIZE)

    @staticmethod
    def generate_pub_key(priv_key):
        return pow(DiffieHellman.g, priv_key, DiffieHellman.p)

    @staticmethod
    def generate_symmetric_key(remote_pub_key, priv_key):
        return pow(remote_pub_key, priv_key, DiffieHellman.p)

class DHPeer(object):
    def __init__(self):
        self.priv_key = DiffieHellman.generate_priv_key()
        self.pub_key = DiffieHellman.generate_pub_key(self.priv_key)
        self.symmetric_key = None
    def get_pub_key(self):
        return self.pub_key
    def establish_session(self, remote_pub_key):
        self.symmetric_key = DiffieHellman.generate_symmetric_key(
                    remote_pub_key, self.priv_key)

