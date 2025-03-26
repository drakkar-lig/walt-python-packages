from cffi import FFI
from walt.server.ext._c_ext.lib import _regcomp, _regfree, _regmatch
from walt.server.ext._c_ext.lib import _regerror_alloc, free;
ffi = FFI()


class PosixExtendedRegex:
    class InvalidRegexException(Exception):
        pass

    def __init__(self, regex):
        self._str_regex = regex.encode('utf-8')
        self._comp_regex = None

    def compile(self):
        if self._comp_regex is None:
            comp_regex = _regcomp(self._str_regex)
            if comp_regex == ffi.NULL:
                c_error = _regerror_alloc(self._str_regex)
                py_error = ffi.string(c_error).decode()
                free(c_error)
                raise PosixExtendedRegex.InvalidRegexException(py_error)
            else:
                # let the garbage collector free the compiled regex when appropriate
                self._comp_regex = ffi.gc(comp_regex, _regfree)

    def match(self, s):
        if self._comp_regex is None:
            self.compile()
        return _regmatch(self._comp_regex, s.encode('utf-8')) > 0
