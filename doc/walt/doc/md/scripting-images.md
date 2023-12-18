# scripting API: image management

Scripting features for image management are available at `walt.client.api.images`:

```
(.venv) ~/experiment$ python3
>>> from walt.client import api
>>> api.images
< -- API submodule for WALT images --

  methods:
  - self.build(self, image_name, dir_or_url): Build an image using a Dockerfile
  - self.clone(self, clonable_image_link, force=False, image_name=None): Clone a remote image into your working set
  - self.get_images(self): Return images of your working set
>
>>>
```


## Building an image

Use API method `api.images.build()`:
```
>>> from walt.client import api
>>> new_image = api.images.build('test-suite-image', "https://github.com/eduble/pc-x86-64-test-suite-mod")
** Cloning the git repository at https://github.com/eduble/pc-x86-64-test-suite-mod
Cloning into '.'...
** Verifying the repository
** Building the image
STEP 1: FROM waltplatform/pc-x86-64-test-suite:latest
STEP 2: ADD testfile /root
STEP 3: RUN echo OK > /root/test-result
STEP 4: COMMIT docker.io/eduble/test-suite-image:latest
Getting image source signatures
Copying blob sha256:c581f4ede92df7272da388a45126ddd2944a4eeb27d3b0d80ee71cd633761394
Copying blob sha256:02ffd0aa707d1c869a40632ffec8b3f4df41d2e0d01cb8bb4aabda3a95469897
Copying blob sha256:0d0da9a827946f2b27eeb2a8a5e9aa2adee0c5751caac15b8b63739e4c02fa33
Copying blob sha256:3180c2adbfcef6e52b95dc459a9d45de52d975cbb2725a90e65aefd03e202753
Copying blob sha256:6df8c0ce6e5c426defe272236c6c8143cadaf8dd341f7b11160538f8b02627d3
Copying blob sha256:21e77f20596e90a04add23b7a417f3ef4d29ef1ca935f2ec6f403a41ca46b55d
Copying blob sha256:929eed5fc9c83ccbd80452e0bee03db07255cbff0223cad7baa54b83c42cc10f
Copying blob sha256:e839f712c8dc36f56a437238515bfee6aaa9a89dec29232365f93fd3e2c80d52
Copying blob sha256:29513c560e2adfeb57b5d4b843f4fe8a09b7e7e6a3457388cad54284e5f7d730
Copying blob sha256:f1492f85162d40a89e073fe6705751e47ef38e76d702183d487870f5db1c0f5e
Copying config sha256:a0b59dc0dd26ff38477bc7d745d5fba030778f4644fb4d6adf9a9ac52ca90eb6
Writing manifest to image destination
Storing signatures
--> a0b59dc0dd2
a0b59dc0dd26ff38477bc7d745d5fba030778f4644fb4d6adf9a9ac52ca90eb6
** Verifying the image
OK
>>>
>>> new_image
< -- image test-suite-image --

  read-only attributes:
  - self.aliases: {'test-suite-image'}
  - self.compatibility: ('pc-x86-64',)
  - self.created: '2023-04-21 10:14:19'
  - self.fullname: 'eduble/test-suite-image:latest'
  - self.id: 'a0b59dc0dd26ff38477bc7d745d5fba030778f4644fb4d6adf9a9ac52ca90eb6'
  - self.in_use: False
  - self.name: 'test-suite-image'

  methods:
  - self.remove(self): Remove this image
  - self.rename(self, new_name): Rename this image
>
>>>
```

Instead of the URL of a git repository, one can also specify a local directory as the 2nd argument.


## Cloning an image

Use API method `api.images.clone()`:
```
>>> new_image = api.images.clone('hub:eduble/pc-x86-64-test-suite')
The image was cloned successfully.
>>>
```

## Managing images

API method `api.images.get_images()` will list the images belonging to your working set.
Your working set is made of the images you previously cloned or built.
A few images (i.e., the default images of node models present on the platform) may have been automatically cloned for you when you first used the walt client tool.

```
>>> images = api.images.get_images()
>>> images
< -- Set of WalT images (5 items) --

  methods:
  - self.filter(self, **kwargs): Return the subset of images matching the given attributes
  - self.get(self, k, default=None): Return item specified or default value if missing
  - self.items(self): Iterate over key & value pairs this set contains
  - self.keys(self): Iterate over keys this set contains
  - self.values(self): Iterate over values this set contains

  sub-items:
  - self['coral-dev-board-mendel']: <image coral-dev-board-mendel>
  - self['openwrt-nfs3']: <image openwrt-nfs3>
  - self['pc-image']: <image pc-image>
  - self['pc-x86-64-test-suite']: <image pc-x86-64-test-suite>
  - self['test-suite-image']: <image test-suite-image>

  note: these sub-items are also accessible using self.<shortcut> for handy completion.
        (use <obj>.<tab><tab> to list these shortcuts)
>
>>> pc_image = images['pc-image']
>>> pc_image
< -- image pc-image --

  read-only attributes:
  - self.aliases: {'pc-x86-64-default', 'pc-image'}
  - self.compatibility: ('pc-x86-64',)
  - self.created: '2022-05-25 15:23:20'
  - self.fullname: 'eduble/pc-image:latest'
  - self.id: 'efa37b66baee1ee74ee42bf18066d70d43f0df1e69c960e16d541f432df424d4'
  - self.in_use: True
  - self.name: 'pc-image'

  methods:
  - self.remove(self): Remove this image
  - self.rename(self, new_name): Rename this image
>
>>> pc_image.compatibility
('pc-x86-64',)
>>>
```

As shown above it is easy to get access to information about a specific image,
and methods for renaming or removing an image are straightforward.


## Booting a WalT image on one or several nodes

See [`walt help show scripting-nodes`](scripting-nodes.md).

