from includes.common import define_test, test_suite_node, test_suite_image, \
                            get_first_items, TEST_IMAGE_URL, skip_test, test_create_vnode
from walt.client import api

def get_existing_vnode():
    nodes = api.nodes.get_nodes()
    node_name = test_suite_node()
    if node_name not in nodes:
        skip_test('requires a vnode but create_vnode test did not create it')
    return nodes[node_name]

@define_test('api.nodes.create_vnode()')
def test_api_nodes_create_vnode():
    test_create_vnode()

@define_test('repr(api.nodes.get_nodes())')
def test_repr_get_nodes():
    # this obviously varies depending on existing nodes,
    # this test just verifies it runs without error
    print(repr(api.nodes.get_nodes()))

@define_test('api node_set.filter()')
def test_api_node_set_filter():
    nodes = api.nodes.get_nodes()
    first_node = get_first_items(nodes, 1, 'walt node')
    set_of_1_node = nodes.filter(name = first_node.name, model = first_node.model)
    if len(set_of_1_node) != 1:
        raise Exception('Unexpected size for resulting node set (should be 1)')

@define_test('api node_set.get()')
def test_api_node_set_get():
    nodes = api.nodes.get_nodes()
    first_node, second_node = get_first_items(nodes, 2, 'walt node')
    if nodes.get(first_node.name) != first_node:
        raise Exception('node_set.get() does not return the expected node')
    if nodes.get(first_node.name, second_node) != first_node:
        raise Exception('node_set.get() does not return the expected node')
    if nodes.get('__missing__node', second_node) != second_node:
        raise Exception('node_set.get() does not return the default value')
    if nodes.get('__missing__node') is not None:
        raise Exception('node_set.get() does not return expected None value')

@define_test('api node_set.items()')
def test_api_node_set_items():
    nodes = api.nodes.get_nodes()
    assert all(item_name == item.name for item_name, item in nodes.items())

@define_test('api node_set.keys()')
def test_api_node_set_keys():
    nodes = api.nodes.get_nodes()
    assert set(nodes.keys()) == set(k for k, v in nodes.items())

@define_test('api node_set.values()')
def test_api_node_set_values():
    nodes = api.nodes.get_nodes()
    assert set(v.name for v in nodes.values()) == set(nodes.keys())

@define_test('api node[.name] in node_set')
def test_api_node_in_node_set():
    nodes = api.nodes.get_nodes()
    first_node = get_first_items(nodes, 1, 'walt node')
    assert first_node in nodes
    assert first_node.name in nodes
    assert '__missing__node' not in nodes

@define_test('api node | node -> node_set')
def test_api_node_binary_or():
    nodes = api.nodes.get_nodes()
    first_node, second_node, third_node = get_first_items(nodes, 3, 'walt node')
    assert first_node in (first_node | second_node | third_node)
    assert first_node not in (second_node | third_node)

@define_test('api node_set[name]')
def test_api_node_set_brackets():
    nodes = api.nodes.get_nodes()
    first_node = get_first_items(nodes, 1, 'walt node')
    assert first_node == nodes[first_node.name]

@define_test('api node_set.<shortcut>')
def test_api_node_set_shortcut():
    nodes = api.nodes.get_nodes()
    shortcut_names = tuple(nodes.__shortcut_names__())
    assert len(shortcut_names) == len(nodes)
    assert all(nodes[k] == getattr(nodes, shortcut) \
            for k, shortcut in shortcut_names)

@define_test('api repr(node)')
def test_api_repr_node():
    nodes = api.nodes.get_nodes()
    first_node = get_first_items(nodes, 1, 'walt node')
    assert first_node.mac in repr(first_node)

@define_test('api node.boot(<image>)')
def test_api_node_boot():
    node = get_existing_vnode()
    image_name = f'{test_suite_image()}-node-boot'
    image = api.images.clone(TEST_IMAGE_URL, force=True, image_name=image_name)
    if image is None or image.name != image_name:
        skip_test('requires an image but cloning fails')
    node.boot(image.name)   # check boot(<image-name>)
    from walt.client.config import conf
    assert node.owner == conf.walt.username
    node.boot('default')    # check boot('default')
    assert node.owner == 'waltplatform'
    node.boot(image)        # check boot(<image-object>)
    assert node.owner == conf.walt.username

@define_test('api node.get_logs()')
def test_api_node_get_logs():
    node = get_existing_vnode()
    # more testing will be done in api-logs.py
    for logline in node.get_logs(history='full'):
        break

@define_test('api node.reboot()')
def test_api_node_reboot():
    node = get_existing_vnode()
    node.reboot(force=True)
    node.reboot(force=True, hard_only=True)

@define_test('api node.wait()')
def test_api_node_wait():
    node = get_existing_vnode()
    node.wait(timeout=90)

@define_test('api node.release()')
def test_api_node_release():
    node = get_existing_vnode()
    node.release()
    assert node.owner == 'waltplatform'

@define_test('api node.acquire()')
def test_api_node_acquire():
    node = get_existing_vnode()
    node.acquire()
    from walt.client.config import conf
    assert node.owner == conf.walt.username

@define_test('api node.rename()')
def test_api_image_rename():
    node = get_existing_vnode()
    name = node.name
    new_name = f'{name}-renamed'
    node.rename(new_name)
    assert node.name == new_name
    assert new_name in api.nodes.get_nodes()
    node.rename(name)

@define_test('api node.remove()')
def test_api_node_remove():
    nodes = api.nodes.get_nodes()
    prefix = test_suite_node()
    for name, node in tuple(nodes.items()):
        if name.startswith(prefix):
            node.remove(force=True)
            if name in nodes:
                raise Exception('Node remove did not work')
    images = api.images.get_images()
    prefix = test_suite_image()
    for name, image in tuple(images.items()):
        if name.startswith(prefix):
            image.remove()
