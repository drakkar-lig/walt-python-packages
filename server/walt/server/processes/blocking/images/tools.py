def update_main_process_about_image(server, image_fullname):
    server.registry.refresh_cache_for_image(image_fullname)
    server.images.store.resync_from_registry()
