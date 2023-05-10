#!dev/python.sh
import sys, atexit
from pathlib import Path
# find imports from the current working directory, not
# from the directory of this source file
sys.path[0] = str(Path().resolve())
from includes.common import set_py_test_mode

def main():
    src_file = Path(sys.argv[1])
    set_py_test_mode(*sys.argv[2:])
    # copy file to make sure it has valid chars for a python module
    test_module = Path() / '__py_test_module.py'
    test_module.write_text(src_file.read_text())
    atexit.register(lambda: test_module.unlink())
    import __py_test_module

if __name__ == '__main__':
    main()
