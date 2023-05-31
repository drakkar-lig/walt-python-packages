# this is the code called by
# $ walt g5k release
from walt.client.g5k.deploy.status import (
    get_last_deployment_status,
    record_end_of_deployment,
)
from walt.client.g5k.tools import run_cmd_on_site
from walt.client.tools import confirm


def release(should_confirm=True):
    info = get_last_deployment_status()
    if info is None:
        print("There is no WalT platform currently deployed.")
        return
    if not should_confirm or confirm():
        for site, site_info in info["sites"].items():
            job_id = site_info.get("job_id")
            if job_id is not None:
                args = ["oardel", job_id]
                run_cmd_on_site(info, site, args, err_out=False)
        record_end_of_deployment(info)
        print("Done.")
