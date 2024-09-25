from cffi import FFI

ffibuilder = FFI()

PROTOTYPES = """
void *_regcomp(char *regex);
int _regmatch(void *preg, char *s);
void _regfree(void *preg);
char *_regerror_alloc(char *regex);
void free(void *ptr);
"""

ffibuilder.cdef(PROTOTYPES)

ffibuilder.set_source(
    "walt.server.ext._posix_regex",  # name of the output C extension
    PROTOTYPES,
    sources=["walt/server/ext/posix_regex.c"],
)  # includes loops.c as additional sources

if __name__ == "__main__":
    ffibuilder.compile(verbose=True)
