from includes.common import define_test

API_ROOT_REPR = '''\
< -- WALT API root --

  read-only attributes:
  - self.images: <API submodule for WALT images>
  - self.logs: <API submodule for WALT logs>
  - self.nodes: <API submodule for WALT nodes>
  - self.tools: <Misc API features>
>'''

@define_test('repr(api)')
def api_root_repr():
    from walt.client import api
    assert repr(api) == API_ROOT_REPR
