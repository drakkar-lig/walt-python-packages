# this is the code called by
# $ walt g5k deploy
import subprocess, sys
from walt.client.g5k.tools import run_cmd_on_site, printed_date_from_ts
from walt.client.g5k.reservation import get_submission_info, JOB_LOGS_DIR
from walt.client.g5k.deploy.status import init_status_info, log_status_change, \
                                          save_deployment_status

def deploy(recipe_info):
    result, info = get_submission_info(recipe_info)
    if result == False:
        tip = info['tip']
        print('Could not deploy this recipe (required resources are not available).')
        print(f'Retry later or edit it (tip: {tip}).')
        return
    init_status_info(info)
    print('Waiting for job submissions... ', end='')
    sys.stdout.flush()
    failure = False
    server_site = info['server']['site']
    submission_processes = {}
    log_status_change(info, 'submission', 'Submitting jobs')
    for site, site_info in info['sites'].items():
        main_job = (site == server_site)
        output = None
        # create main job log dirs
        if main_job:
            output = run_cmd_on_site(info, site,
                    [ "mkdir", "-p", JOB_LOGS_DIR ], err_out=False)
        # if ok, submit the job
        if not isinstance(output, subprocess.CalledProcessError):
            args = site_info['submit_args']
            output = run_cmd_on_site(
                        info, site, args, err_out=False, background=True)
        # if error, print it
        if isinstance(output, subprocess.CalledProcessError):
            print('FAILED submission at ' + site)
            print(output, file=sys.stderr)
            print(output.stdout, file=sys.stderr)
            failure = True
            break
        submission_processes[site] = output
    for site, process_output in submission_processes.items():
        site_job_id = None
        output_lines = []
        try:
            for line in process_output:
                output_lines += [ line ]
                if 'OAR_JOB_ID=' in line:
                    site_job_id = line.strip().split('=')[1]
                    info['sites'][site]['job_id'] = site_job_id
        except Exception as e:
            pass
        if site_job_id is None:
            print('FAILED submission at ' + site)
            print('\n'.join(output_lines), file=sys.stderr)
            failure = True
        process_output.close()
    if failure:
        successful_sites = [ site for (site, site_info) in info['sites'].items() \
                             if 'job_id' in site_info ]
        if len(successful_sites) > 0:
            print("Cancelling previous submissions on other sites... ", end='')
            sys.stdout.flush()
            for site in successful_sites:
                job_id = info['sites'][site]['job_id']
                args = [ 'oardel', job_id ]
                run_cmd_on_site(info, site, args, err_out=False)
            print('done.')
        sys.exit(1)
    print('done.')
    scheduled_start = printed_date_from_ts(info["start_date"])
    log_status_change(info, 'waiting.schedule', 'Waiting for scheduled start: ' + scheduled_start)
    # record in advance in the history that at "start_date", we will be waiting
    # for the main job to start.
    info['history']['jobs.main.waiting'] = info["start_date"]
    save_deployment_status(info)
    print('A G5K job will deploy your WalT platform at: ' + scheduled_start)
    print("Use 'walt g5k wait' to wait until your WalT platform is ready.")
    print("Use 'walt g5k release' to cancel this deployment.")
