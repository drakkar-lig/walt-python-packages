#!dev/python.sh
import atexit
import sys
from pathlib import Path

# find imports from the test directory, not
# from the directory of this source file
root_dir = Path(__file__).parent.parent
test_dir = root_dir / 'test'
sys.path[0] = str(test_dir.resolve())
from includes.common import set_py_test_mode  # noqa: E402


def main():
    src_file = Path(sys.argv[1])
    set_py_test_mode(*sys.argv[2:])
    # copy file to make sure it has valid chars for a python module
    test_module = test_dir / '__py_test_module.py'
    test_module.write_text(src_file.read_text())
    atexit.register(lambda: test_module.unlink())
    import __py_test_module  # noqa: F401

if __name__ == '__main__':
    main()
