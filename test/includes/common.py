
import os, sys
from pathlib import Path

TEST_IMAGE_URL='hub:eduble/pc-x86-64-test-suite'

def test_suite_image():
    p = Path('/tmp/test_suite_image')
    if not p.exists():
        p.write_text(f'pc-x86-64-test-suite-{os.getpid()}\n')
    return p.read_text().strip()

def test_suite_node():
    p = Path('/tmp/test_suite_node')
    if not p.exists():
        p.write_text(f'testnode-{os.getpid()}\n')
    return p.read_text().strip()

TEST_CONTEXT = {
}

def set_py_test_mode(mode, num_test=0):
    TEST_CONTEXT['mode'] = mode
    TEST_CONTEXT['num_test'] = int(num_test)

def define_test(s):
    if TEST_CONTEXT['mode'] == 'describe':
        print(TEST_CONTEXT['num_test'], s)
        TEST_CONTEXT['num_test'] += 1
        def decorate(f):
            pass
    elif TEST_CONTEXT['mode'] == 'run':
        if TEST_CONTEXT['num_test'] == 0:
            def decorate(f):
                f()
        else:
            def decorate(f):
                pass
        TEST_CONTEXT['num_test'] -= 1
    return decorate

def skip_test(reason):
    skip_notify_file = Path(os.environ['TESTSUITE_TMP_DIR']) / 'skipped'
    skip_notify_file.write_text(reason)
    sys.exit(1)
