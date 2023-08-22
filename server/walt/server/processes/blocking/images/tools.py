import time

def update_main_process_about_image(server, image_fullname):
    while not server.registry.image_exists(image_fullname):
        print('Waiting for the image to be detected in main registry.')
        time.sleep(0.5)
    server.registry.refresh_cache_for_image(image_fullname)
    server.images.store.resync_from_registry()
