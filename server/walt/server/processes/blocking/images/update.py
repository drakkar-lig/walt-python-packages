import asyncio

from collections import defaultdict
from walt.server.processes.blocking.images.search import Search
from walt.server.processes.blocking.registries import MissingRegistryCredentials
from walt.server.tools import async_gather_tasks


async def async_check_image_update(
        updates, registry, requester,
        fullname, location, walt_created_ts):
    registry_created_ts = await registry.async_get_created_ts(requester, fullname)
    print(fullname, location, walt_created_ts, registry_created_ts)
    if walt_created_ts < registry_created_ts:
        updates[fullname].append((registry_created_ts, location, registry))


async def async_update_default_images(requester, server, update_info):
    requester.stdout.write(f'Checking remote registries...\n')
    def validate(image_name, user, location):
        return f"{user}/{image_name}" in update_info
    search = Search(None, requester, validate, output_registries=True)
    it = search.async_search()
    updates = defaultdict(list)
    tasks = []
    async for registry, fullname, location, labels in it:
        walt_created_ts = update_info[fullname]
        tasks += [asyncio.create_task(
                    async_check_image_update(
                        updates, registry, requester,
                        fullname, location, walt_created_ts))]
    await async_gather_tasks(tasks)
    if len(updates) > 0:
        for fullname, update_candidates in updates.items():
            newest = sorted(update_candidates, reverse=True)[0]
            registry_created_ts, location, registry = newest
            requester.stdout.write(
                f'Updating {fullname} using a newer version from {location}...\n')
            registry.pull(requester, server, fullname)
        server.images.store.resync_from_registry()
        server.images.store.trigger_update_image_mounts()
    else:
        requester.stdout.write('No updates available.\n')
    # return the list of updated image fullnames
    return tuple(updates.keys())


# this implements walt advanced update-default-images
def update_default_images(requester, server, update_info):
    try:
        return ('OK', asyncio.run(
            async_update_default_images(requester, server, update_info)))
    except MissingRegistryCredentials as e:
        return ('MISSING_REGISTRY_CREDENTIALS', e.registry_label)
