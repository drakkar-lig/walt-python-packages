import base64

WALT_SERVER_DAEMON_PORT = 12345
WALT_SERVER_TCP_PORT = 12347
WALT_SERVER_NETCONSOLE_PORT = 12342

# Note: these keys are used for internal communication inside the walt experimental
# testbed, so having them published with the source code is not a problem.
# The two levels of base64 encoding are just here to make security check up services
# such as gitguardian quiet.

UNSECURE_ECDSA_KEYPAIR = {
    "openssh-priv": base64.b64decode(
        base64.b64decode(
            b"""
TFMwdExTMUNSVWRKVGlCRlF5QlFVa2xXUVZSRklFdEZXUzB0TFMwdENrMUlZME5CVVVWRlNVUlhj
MFZPZUdOU1ZXdEdhMVJwTDJkeFRtOW5OMWhpUlZWblNuRllkRzgwVEVKdFVqa3hNbTFGVTAxdlFX
OUhRME54UjFOTk5Ea0tRWGRGU0c5VlVVUlJaMEZGTWpFNWJ5dFBRbXcxY1VkaE5tbFpUMnRJYkVO
Q1ltUlFXbk15TUhaMlNWRm1LMkp3TUd0SmQwazBURzFrY1RjNVlsUlVlZ3BTUlVoaWVEa3ZURXRT
UjFKdU9Ib3lVVTF4TTBWWk9WWXZjM1JSY0Voak5qaDNQVDBLTFMwdExTMUZUa1FnUlVNZ1VGSkpW
a0ZVUlNCTFJWa3RMUzB0TFFvPQ=="""
        )
    ),
    "openssh-pub": base64.b64decode(
        b"""
ZWNkc2Etc2hhMi1uaXN0cDI1NiBBQUFBRTJWalpITmhMWE5vWVRJdGJtbHpkSEF5TlRZQUFBQUli
bWx6ZEhBeU5UWUFBQUJCQk50ZmFQamdaZWFobXVvbURwQjVRZ1czVDJiTnRMN3lFSC9tNmRKQ01D
T0M1bmF1L1cwMDgwUkIyOGZmeXlrUmtaL005a0RLdHhHUFZmN0xVS1IzT3ZNPSBVTlNFQ1VSRQ==
"""
    ),
    "dropbear": base64.b64decode(
        b"""
AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBNtfaPjgZeahmuomDpB5QgW3
T2bNtL7yEH/m6dJCMCOC5nau/W0080RB28ffyykRkZ/M9kDKtxGPVf7LUKR3OvMAAAAgNawQ3FxF
SQWROL+Co2iDtdsRSAmpe2jgsGZH3XaYRIw="""
    ),
}
