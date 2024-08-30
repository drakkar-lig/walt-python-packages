from includes.common import (
    define_test,
    test_create_vnode,
    get_vnode,
    test_json_request
)


@define_test("web api/v1/images")
def test_api_images():
    # create a vnode and check we find its image in web api response
    vnode = test_create_vnode()
    json_images = test_json_request("images")
    assert len(json_images) > 0
    img_name = vnode.image.fullname
    filtered = [ d for d in json_images if d.get("fullname", "") == img_name ]
    assert len(filtered) == 1
    json_image = filtered[0]
    assert len(json_image.keys()) == 6
    for k in ('fullname', 'id', 'in_use', 'created'):
        assert json_image.get(k, None) == getattr(vnode.image, k, None)
    assert json_image.get("user", None) == img_name.split("/")[0]
    assert json_image.get("compatibility", []) == list(vnode.image.compatibility)


@define_test("web api/v1/images?in_use=<true|false>")
def test_api_images_filter_in_use():
    json_images_all = test_json_request("images")
    json_images_in_use = test_json_request("images", in_use="true")
    json_images_not_in_use = test_json_request("images", in_use="false")
    assert len(json_images_all) == (
            len(json_images_in_use) + len(json_images_not_in_use))
    vnode = get_vnode()
    vnode.remove(force=True)  # last test of file, cleanup
