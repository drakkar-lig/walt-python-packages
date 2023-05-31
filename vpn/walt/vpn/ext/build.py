from cffi import FFI

ffibuilder = FFI()

PROTOTYPES = """
int client_transmission_loop(int ssh_stdin, int ssh_stdout, int tap_fd);
void endpoint_transmission_loop(int tap_fd);
"""

ffibuilder.cdef(PROTOTYPES)

ffibuilder.set_source(
    "walt.vpn.ext._loops",  # name of the output C extension
    PROTOTYPES,
    sources=["walt/vpn/ext/loops.c"],
)  # includes loops.c as additional sources

if __name__ == "__main__":
    ffibuilder.compile(verbose=True)
