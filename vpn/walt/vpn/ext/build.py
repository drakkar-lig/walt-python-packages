from cffi import FFI
ffibuilder = FFI()

PROTOTYPES = """
int client_transmission_loop(int lengths_stdin, int lengths_stdout,
                             int packets_stdin, int packets_stdout, int tap_fd);
void server_transmission_loop(int(*on_connect)(), int(*on_disconnect)(int));
"""

ffibuilder.cdef(PROTOTYPES)

ffibuilder.set_source("walt.vpn.ext._loops",  # name of the output C extension
    PROTOTYPES,
    sources=['walt/vpn/ext/loops.c'])   # includes loops.c as additional sources

if __name__ == "__main__":
    ffibuilder.compile(verbose=True)

