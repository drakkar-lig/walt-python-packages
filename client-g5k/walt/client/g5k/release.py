# this is the code called by
# $ walt g5k release
from walt.client.g5k.deploy.status import get_deployment_status, forget_deployment
from walt.client.g5k.tools import run_cmd_on_site
from walt.client.tools import confirm

def release():
    info = get_deployment_status(err_out=False)
    if info is None:
        print('There is no WalT platform currently deployed.')
        return
    if confirm():
        for (site, site_info) in info['sites'].items():
            job_id = site_info['job_id']
            args = [ 'oardel', job_id ]
            run_cmd_on_site(info, site, args)
        forget_deployment()
        print('Done.')
