from walt.common.tools import get_kernel_bootarg

def lookup_server_ip():
    return get_kernel_bootarg('walt.server.ip')
