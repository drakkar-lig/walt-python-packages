import tempfile
from pathlib import Path

from includes.common import (
    TEST_IMAGE_URL,
    define_test,
    get_first_items,
    test_suite_image,
)
from walt.client import api
from walt.common.tools import do

IMAGE_BUILD_GIT_URL = "https://github.com/eduble/pc-x86-64-test-suite-mod"
IMAGE_CLONE_NAME = f'{test_suite_image()}-api-clone'
IMAGE_RENAME_NAME = f'{test_suite_image()}-api-rename'

@define_test('api.images.build()')
def test_walt_image_build():
    image_name_dir = f'{test_suite_image()}-api-bdir'
    image_name_url = f'{test_suite_image()}-api-burl'
    with tempfile.TemporaryDirectory() as tmpdirname:
        tmpdir = Path(tmpdirname)
        # build from dir
        do(f'git clone {IMAGE_BUILD_GIT_URL} {tmpdirname}')
        api.images.build(image_name_dir, tmpdir)
        images = api.images.get_images()
        images[image_name_dir].remove()
        # build from url
        api.images.build(image_name_url, IMAGE_BUILD_GIT_URL)
        images = api.images.get_images()
        images[image_name_url].remove()
        # note: the validity of built images is already verified
        # by the cli test of 'walt image build'

@define_test('api.images.clone()')
def test_api_images_clone():
    api.images.clone(TEST_IMAGE_URL, force=True, image_name=IMAGE_CLONE_NAME)
    images = api.images.get_images()
    if IMAGE_CLONE_NAME not in images:
        raise Exception(f'Could not find "{IMAGE_CLONE_NAME}" in images')

@define_test('api image.rename()')
def test_api_image_rename():
    images = api.images.get_images()
    images[IMAGE_CLONE_NAME].rename(IMAGE_RENAME_NAME)
    if IMAGE_CLONE_NAME in images or IMAGE_RENAME_NAME not in images:
        raise Exception('Image rename did not work')

@define_test('repr(api.images.get_images())')
def test_repr_get_images():
    # this obviously varies depending on existing images,
    # this test just verifies it runs without error
    print(repr(api.images.get_images()))

@define_test('api image_set.filter()')
def test_api_image_set_filter():
    images = api.images.get_images()
    first_image = get_first_items(images, 1, 'walt image')
    set_of_1_image = images.filter(name = first_image.name, created = first_image.created)
    if len(set_of_1_image) != 1:
        raise Exception('Unexpected size for resulting image set (should be 1)')

@define_test('api image_set.get()')
def test_api_image_set_get():
    images = api.images.get_images()
    first_image, second_image = get_first_items(images, 2, 'walt image')
    if images.get(first_image.name) != first_image:
        raise Exception('image_set.get() does not return the expected image')
    if images.get(first_image.name, second_image) != first_image:
        raise Exception('image_set.get() does not return the expected image')
    if images.get('__missing__image', second_image) != second_image:
        raise Exception('image_set.get() does not return the default value')
    if images.get('__missing__image') is not None:
        raise Exception('image_set.get() does not return expected None value')

@define_test('api image_set.items()')
def test_api_image_set_items():
    images = api.images.get_images()
    assert all(item_name == item.name for item_name, item in images.items())

@define_test('api image_set.keys()')
def test_api_image_set_keys():
    images = api.images.get_images()
    assert set(images.keys()) == set(k for k, v in images.items())

@define_test('api image_set.values()')
def test_api_image_set_values():
    images = api.images.get_images()
    assert set(v.name for v in images.values()) == set(images.keys())

@define_test('api image[.name] in image_set')
def test_api_image_in_image_set():
    images = api.images.get_images()
    first_image = get_first_items(images, 1, 'walt image')
    assert first_image in images
    assert first_image.name in images
    assert '__missing__image' not in images

@define_test('api image | image -> image_set')
def test_api_image_binary_or():
    images = api.images.get_images()
    first_image, second_image, third_image = get_first_items(images, 3, 'walt image')
    assert first_image in (first_image | second_image | third_image)
    assert first_image not in (second_image | third_image)

@define_test('api image_set[name]')
def test_api_image_set_brackets():
    images = api.images.get_images()
    first_image = get_first_items(images, 1, 'walt image')
    assert first_image == images[first_image.name]

@define_test('api image_set.<shortcut>')
def test_api_image_set_shortcut():
    images = api.images.get_images()
    shortcut_names = tuple(images.__shortcut_names__())
    assert len(shortcut_names) == len(images)
    assert all(images[k] == getattr(images, shortcut) \
            for k, shortcut in shortcut_names)

@define_test('api repr(image)')
def test_api_repr_image():
    images = api.images.get_images()
    first_image = get_first_items(images, 1, 'walt image')
    assert first_image.id in repr(first_image)

@define_test('api image.remove()')
def test_api_image_remove():
    images = api.images.get_images()
    prefix = test_suite_image()
    for name, image in tuple(images.items()):
        if name.startswith(prefix):
            image.remove()
            if name in images:
                raise Exception('Image remove did not work')

