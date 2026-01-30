# Client registry configuration sometimes involves calls
# to the server (e.g. CSAPI.registry_login("hub")), to check
# that the input provided is correct.
# Most of the work we do when interacting with registries
# is delegated to the blocking process. This blocking process
# handles requests one at a time, so it cannot call client
# configuration fixup functions directly, because those
# functions may trigger calls back to this blocking process
# currently busy.
# That's why we leverage the main process here, which
# is reentrant.

# Here is a possible scenario:

# client code for `walt image clone hub:<something>`
# -> server main code
#    -> server blocking code calls
#       requester.ensure_registry_enabled("hub")
#       -> server main passes the request to client
#          -> client checks and returns False
#          <-
#       <-
#       server blocking code raises an Exception,
#       and returns ("OP_ON_DISABLED_REGISTRY",)
#    <-
#    server main code calls the err fixup code
#    defined below.
#    -> client propose_enable_registry() code:
#       the user answers yes and enters its
#       registry credentials, then it verifies
#       those credentials by trying to log in.
#       -> server main passes the login request
#          to blocking process
#          -> the blocking process logs in successfully
#          <-
#       <-
#       the client saves these valid credentials
#       and enables this registry in conf.
#    <-
#    server main code (here) continues by restarting
#    the initial blocking function for image clone
#    -> server blocking code calls
#       requester.ensure_registry_enabled("hub")
#       -> server main passes the request to client
#          -> client checks and returns True this time
#          <-
#       <-
#       server blocking code proceeds with image
#       cloning code
#    <-
# <-
# done.

# When we look at this process, there were several
# reentrant calls to server-main, but none to
# server-blocking.

def handle_client_registry_conf_issues(requester, blocking_func, result_cb):
    assert requester is not None
    def cb(result):
        error_cases = {
            'MISSING_REGISTRY_CONF': (
                    requester.prompt_missing_registry_conf,
                    "The registry is not configured!",
            ),
            'MISSING_REGISTRY_CREDENTIALS': (
                    requester.prompt_missing_registry_credentials,
                    "Missing registry credentials!",
            ),
            'OP_ON_DISABLED_REGISTRY': (
                    requester.propose_enable_registry,
                    "Operation on disabled registry!",
            ),
        }
        err_fixup, err_msg = error_cases.get(result[0], (None, None))
        if err_fixup is not None:
            registry_label = result[1]
            res = err_fixup(registry_label)
            if res == True:
                # ok, fixed up, retry once more
                # (and we may need several fixups)
                handle_client_registry_conf_issues(
                        requester, blocking_func, result_cb)
            else:
                # not fixed up, return with failure status
                result_cb(('FAILED', err_msg))
        else:
            result_cb(result)
    blocking_func(cb)
