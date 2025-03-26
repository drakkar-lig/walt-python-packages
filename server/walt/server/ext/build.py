from cffi import FFI

ffibuilder = FFI()

PROTOTYPES = """
void *_regcomp(char *regex);
int _regmatch(void *preg, char *s);
void _regfree(void *preg);
char *_regerror_alloc(char *regex);
void free(void *ptr);
void _vpn_endpoint_transmission_loop(int tap_fd);
"""

ffibuilder.cdef(PROTOTYPES)

ffibuilder.set_source(
    "walt.server.ext._c_ext",  # name of the output C extension
    PROTOTYPES,
    sources=["walt/server/ext/posix_regex.c",
             "walt/server/ext/vpn.c"],
)

if __name__ == "__main__":
    ffibuilder.compile(verbose=True)
