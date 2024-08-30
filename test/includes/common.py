import os
import requests
import sys
from pathlib import Path
from walt.client import api

TEST_IMAGE_URL = "hub:eduble/pc-x86-64-test-suite"


def test_suite_image():
    p = Path("/tmp/test_suite_image")
    if not p.exists():
        p.write_text(f"pc-x86-64-test-suite-{os.getpid()}\n")
    return p.read_text().strip()


def test_suite_node():
    p = Path("/tmp/test_suite_node")
    if not p.exists():
        p.write_text(f"testnode-{os.getpid()}\n")
    return p.read_text().strip()


def test_create_vnode():
    node_name = test_suite_node()
    node = api.nodes.create_vnode(node_name)
    assert node.name == node_name
    assert node_name in api.nodes.get_nodes()
    return node


def get_vnode():
    return api.nodes.get_nodes()[test_suite_node()]


TEST_CONTEXT = {}


def set_py_test_mode(mode, num_test=0):
    TEST_CONTEXT["mode"] = mode
    TEST_CONTEXT["num_test"] = int(num_test)


def define_test(s):
    if TEST_CONTEXT["mode"] == "describe":
        print(TEST_CONTEXT["num_test"], s)
        TEST_CONTEXT["num_test"] += 1

        def decorate(f):
            pass

    elif TEST_CONTEXT["mode"] == "run":
        if TEST_CONTEXT["num_test"] == 0:

            def decorate(f):
                f()

        else:

            def decorate(f):
                pass

        TEST_CONTEXT["num_test"] -= 1
    return decorate


def skip_test(reason):
    skip_notify_file = Path(os.environ["TESTSUITE_TMP_DIR"]) / "skipped"
    skip_notify_file.write_text(reason)
    sys.exit(1)


def get_first_items(item_set, n_items, item_label):
    it = iter(item_set)
    result = []
    try:
        for _ in range(n_items):
            result.append(next(it))
    except StopIteration:
        skip_test(f"requires at least two {item_label}s")
    if n_items == 1:
        return result[0]
    else:
        return tuple(result)


def test_json_request(items_word, status_code=200, dict_params=None, **params):
    url = f"http://localhost/api/v1/{items_word}"
    if dict_params is not None:
        params.update(dict_params)
    if len(params) > 0:
        url += "?" + "&".join(f"{k}={v}" for (k, v) in params.items())
    print(url)
    resp = requests.get(url)
    assert resp.status_code == status_code
    if status_code == 200:
        json_resp = resp.json()
        num_items = json_resp.get(f"num_{items_word}")
        items_list = json_resp.get(items_word, [])
        assert num_items == len(items_list)
        return items_list


