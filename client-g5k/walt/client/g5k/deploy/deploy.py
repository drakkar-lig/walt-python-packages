# this is the code called by
# $ walt g5k deploy
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from walt.client.g5k.deploy.status import (
    exit_if_walt_platform_deployed,
    init_status_info,
    log_status_change,
    save_deployment_status,
)
from walt.client.g5k.reservation import (
    DEFAULT_START_TIME_MARGIN_SECS,
    get_submission_info,
)
from walt.client.g5k.tools import printed_date_from_ts, run_cmd_on_site

# if the jobs submission took too long, and the scheduled start is
# too close or already past, jobs may not work properly.
SUBMISSION_MARGIN_SECS = 1 * 60

# Error codes
SUBMISSION_ERROR = 1
SUBMISSION_MISSING_RESOURCES = 2


def cancel_jobs(info):
    successful_sites = [
        site for (site, site_info) in info["sites"].items() if "job_id" in site_info
    ]
    if len(successful_sites) > 0:
        print("Cancelling previous submissions... ", end="")
        sys.stdout.flush()
        for site in successful_sites:
            job_id = info["sites"][site]["job_id"]
            args = ["oardel", job_id]
            run_cmd_on_site(info, site, args, err_out=False)
        print("done.")


def deploy(recipe_info):
    exit_if_walt_platform_deployed()
    start_time_margin = DEFAULT_START_TIME_MARGIN_SECS
    while True:
        deployment_id = datetime.now().strftime("%Y-%m-%d--%H-%M-%S")
        print("Analysing recipe and available resources... ", end="")
        sys.stdout.flush()
        result, info = get_submission_info(
            recipe_info, deployment_id, start_time_margin
        )
        if result is False:
            tip = info["tip"]
            print("FAILED")
            print(
                "Could not deploy this recipe (required resources are not available)."
            )
            print(f"Retry later or edit it (tip: {tip}).")
            return
        print("OK")
        init_status_info(info, deployment_id)
        logs_dir = info["logs_dir"]
        Path(logs_dir).mkdir(parents=True)
        print("Waiting for job submissions... ", end="")
        sys.stdout.flush()
        failure = None
        server_site = info["server"]["site"]
        submission_processes = {}
        log_status_change(info, "submission", "Submitting jobs")
        for site, site_info in info["sites"].items():
            main_job = site == server_site
            output = None
            # create main job log dirs
            if main_job:
                output = run_cmd_on_site(
                    info, site, ["mkdir", "-p", logs_dir], err_out=False
                )
            # if ok, submit the job
            if not isinstance(output, subprocess.CalledProcessError):
                args = site_info["submit_args"]
                output = run_cmd_on_site(
                    info, site, args, err_out=False, background=True
                )
            # if error, print it
            if isinstance(output, subprocess.CalledProcessError):
                if failure is None:
                    print("FAILED")
                print("FAILED submission at " + site)
                print(output, file=sys.stderr)
                print(output.stdout, file=sys.stderr)
                failure = SUBMISSION_ERROR
                break
            submission_processes[site] = output
        for site, process_output in submission_processes.items():
            site_job_id = None
            output_lines = []
            try:
                for line in process_output:
                    output_lines += [line]
                    if "OAR_JOB_ID=" in line:
                        site_job_id = line.strip().split("=")[1]
                        info["sites"][site]["job_id"] = site_job_id
                    if "not valid" in line:
                        if failure is None:
                            print("FAILED")
                        failure = SUBMISSION_MISSING_RESOURCES
                        print(
                            f"Some planned resources are no longer available at {site}."
                        )
            except Exception:
                pass
            if site_job_id is None:
                if failure is None:
                    print("FAILED")
                print("FAILED submission at " + site)
                print("\n".join(output_lines), file=sys.stderr)
                failure = SUBMISSION_ERROR
            process_output.close()
        if failure == SUBMISSION_MISSING_RESOURCES:
            cancel_jobs(info)
            print("Retrying.")
            continue
        if failure is None:
            now = time.time()
            if now > info["start_date"] - SUBMISSION_MARGIN_SECS:
                print("FAILED")
                print("Job submission took too long.")
                cancel_jobs(info)
                print("Retrying with a larger margin before start time.")
                start_time_margin *= 2
                continue
        if failure is not None:
            cancel_jobs(info)
            sys.exit(1)
        print("done.")
        break
    scheduled_start = printed_date_from_ts(info["start_date"])
    log_status_change(
        info, "waiting.schedule", "Waiting for scheduled start: " + scheduled_start
    )
    # record in advance in the history that at "start_date", we will be waiting
    # for the main job to start.
    info["history"]["jobs.main.waiting"] = info["start_date"]
    save_deployment_status(info)
    print("A G5K job will deploy your WalT platform at: " + scheduled_start)
    print("Use 'walt g5k wait' to wait until your WalT platform is ready.")
    print("Use 'walt g5k release' to cancel this deployment.")
