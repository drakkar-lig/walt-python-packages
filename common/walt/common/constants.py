
WALT_SERVER_DAEMON_PORT = 12345
WALT_SERVER_TCP_PORT = 12347
WALT_SERVER_NETCONSOLE_PORT = 12342

UNSECURE_ECDSA_KEYPAIR = {
    "openssh-priv": """\
-----BEGIN EC PRIVATE KEY-----
MHcCAQEEIDWsENxcRUkFkTi/gqNog7XbEUgJqXto4LBmR912mESMoAoGCCqGSM49
AwEHoUQDQgAE219o+OBl5qGa6iYOkHlCBbdPZs20vvIQf+bp0kIwI4Lmdq79bTTz
REHbx9/LKRGRn8z2QMq3EY9V/stQpHc68w==
-----END EC PRIVATE KEY-----
""",
    "openssh-pub": """\
ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBNtfaPjgZeahmuomDpB5QgW3T2bNtL7yEH/m6dJCMCOC5nau/W0080RB28ffyykRkZ/M9kDKtxGPVf7LUKR3OvM= UNSECURE\
""",
    "dropbear": """\
\x00\x00\x00\x13ecdsa-sha2-nistp256\x00\x00\x00\x08nistp256\x00\x00\x00A\x04\xdb_h\xf8\xe0e\xe6\xa1\x9a\xea&\x0e\x90yB\x05\xb7Of\xcd\xb4\xbe\xf2\x10\x7f\xe6\xe9\xd2B0#\x82\xe6v\xae\xfdm4\xf3DA\xdb\xc7\xdf\xcb)\x11\x91\x9f\xcc\xf6@\xca\xb7\x11\x8fU\xfe\xcbP\xa4w:\xf3\x00\x00\x00 5\xac\x10\xdc\\EI\x05\x918\xbf\x82\xa3h\x83\xb5\xdb\x11H\t\xa9{h\xe0\xb0fG\xddv\x98D\x8c"""
}
