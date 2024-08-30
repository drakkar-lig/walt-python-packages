from includes.common import (
    define_test,
    test_create_vnode,
    get_vnode,
    test_json_request
)


@define_test("web api/v1/nodes")
def test_api_nodes():
    vnode = test_create_vnode()
    json_nodes = test_json_request("nodes")
    assert len(json_nodes) > 0
    filtered_json_nodes = [ d for d in json_nodes if d.get("name", "") == vnode.name ]
    assert len(filtered_json_nodes) == 1
    json_vnode = filtered_json_nodes[0]
    assert len(json_vnode.keys()) == 8
    for k in ('name', 'model', 'virtual', 'booted', 'ip', 'mac'):
        assert json_vnode.get(k, None) == getattr(vnode, k, None)
    assert json_vnode.get("image", None) == vnode.image.fullname
    json_vnode_config = json_vnode.get("config", {})
    for k, v in json_vnode_config.items():
        v == getattr(vnode.config, k.replace(".", "_"), None)


@define_test("web api/v1/nodes?mac=<mac>")
def test_api_nodes_filter_mac():
    vnode = get_vnode()
    json_nodes = test_json_request("nodes", mac=vnode.mac)
    assert len(json_nodes) == 1
    assert json_nodes[0]["name"] == vnode.name


@define_test("web api/v1/nodes?booted=<true|false>")
def test_api_nodes_filter_booted():
    json_nodes_all = test_json_request("nodes")
    json_nodes_booted = test_json_request("nodes", booted="true")
    json_nodes_not_booted = test_json_request("nodes", booted="false")
    assert len(json_nodes_all) == len(json_nodes_booted) + len(json_nodes_not_booted)
    vnode = get_vnode()
    vnode.remove(force=True)  # last test of file, cleanup
