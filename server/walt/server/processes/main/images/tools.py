def handle_missing_credentials(requester, blocking_func, result_cb):
    def cb(result):
        if result[0] == 'MISSING_REGISTRY_CREDENTIALS':
            registry_label = result[1]
            requester.prompt_missing_registry_credentials(registry_label)
            # retry once more
            blocking_func(result_cb)
        else:
            result_cb(result)
    blocking_func(cb)
