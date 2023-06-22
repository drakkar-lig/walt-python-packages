import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

from walt.client import __version__
from walt.client.g5k.myexeco import load_execo_g5k
from walt.client.g5k.tools import get_local_g5k_site

POSSIBLE_CLUSTERS_FOR_SERVER = None
WALT_SERVER_ENV_FILE = (
    f"http://public.grenoble.grid5000.fr/~eduble/walt-server-{__version__}.yaml"
)
DEBUG_MODE = False
# default planning start time is 1 minute from now
# in some cases this is not enough time for submitting the jobs.
DEFAULT_START_TIME_MARGIN_SECS = 2 * 60


def compute_possible_clusters_for_server():
    global POSSIBLE_CLUSTERS_FOR_SERVER
    POSSIBLE_CLUSTERS_FOR_SERVER = {}
    execo_g5k = load_execo_g5k()
    for cluster in execo_g5k.get_g5k_clusters("default"):
        first_cluster_host = execo_g5k.get_cluster_hosts(cluster)[0]
        cluster_attr = execo_g5k.get_host_attributes(first_cluster_host)
        if cluster_attr["exotic"]:
            continue
        if len(cluster_attr["kavlan"]) < 2:
            continue
        # ok hosts on this cluster have 2 or more network adapters
        # which we can connect to different VLANs
        site = execo_g5k.get_cluster_site(cluster)
        if site not in POSSIBLE_CLUSTERS_FOR_SERVER:
            POSSIBLE_CLUSTERS_FOR_SERVER[site] = [cluster]
        else:
            POSSIBLE_CLUSTERS_FOR_SERVER[site].append(cluster)


def get_possible_clusters_for_server():
    if POSSIBLE_CLUSTERS_FOR_SERVER is None:
        compute_possible_clusters_for_server()
    return POSSIBLE_CLUSTERS_FOR_SERVER


def get_g5k_sites_for_walt_server():
    return list(get_possible_clusters_for_server())


def get_g5k_sites():
    execo_g5k = load_execo_g5k()
    return execo_g5k.get_g5k_sites()


def filter_vlans_from_planning(planning, vlan_type="kavlan-local"):
    for site in planning:
        vlans = planning[site]["vlans"]
        for vlan_name in tuple(vlans.keys()):
            vlan_num = int(vlan_name.split("-")[1])
            if vlan_type == "kavlan-local":
                drop_vlan = vlan_num > 3
            else:  # vlan_type == 'kavlan-global'
                drop_vlan = vlan_num < 10
            if drop_vlan:
                del vlans[vlan_name]


def analyse_reservation(recipe_info, start_time_margin=DEFAULT_START_TIME_MARGIN_SECS):
    execo_g5k = load_execo_g5k()
    walltime = recipe_info["walltime"]
    g5k_node_counts = {
        site: num for (site, num) in recipe_info["node_counts"].items() if num > 0
    }
    # add one g5k node for walt server
    server_site = recipe_info["server"]["site"]
    g5k_node_counts[server_site] = g5k_node_counts.get(server_site, 0) + 1
    out_of_chart = recipe_info["schedule"] == "night"
    resources_wanted = dict(kavlan=1, **g5k_node_counts)
    if len(g5k_node_counts.keys()) == 1:
        vlan_type = "kavlan-local"
    else:
        vlan_type = "kavlan-global"
        # reference other sites in resources_wanted too because we may want
        # to use their global vlan
        for site in get_g5k_sites():
            if site not in resources_wanted:
                resources_wanted[site] = 0
    planning = execo_g5k.planning.get_planning(
        starttime=time.time() + start_time_margin,
        elements=resources_wanted,
        vlan=True,
        out_of_chart=out_of_chart,
    )
    filter_vlans_from_planning(planning, vlan_type)
    slots = execo_g5k.planning.compute_slots(planning, walltime)
    return find_free_slot(recipe_info, vlan_type, slots, resources_wanted)


def slot_has_a_node_suitable_for_server(recipe_info, slot):
    server_site = recipe_info["server"]["site"]
    candidate_clusters = get_possible_clusters_for_server()[server_site]
    for element, value in slot[2].items():
        if element in candidate_clusters:
            if value >= 1:
                return True
    return False


def slot_has_kavlan(slot):
    for element, value in slot[2].items():
        if element == "kavlan":
            if isinstance(value, list):  # kavlan-global
                return len(value) > 0
            else:  # kavlan-local: value is int
                return value > 0
    return False


def slot_has_requested_nodes(slot, resources_wanted):
    for element, value in slot[2].items():
        if (
            element != "kavlan"
            and element in resources_wanted
            and resources_wanted[element] > value
        ):
            return False
    return True


def is_maintenance_slot(slot):
    for element, value in slot[2].items():
        if isinstance(value, int):
            if value > 0:
                return False
    return True  # all resources are 0 => maintenance slot


# execo provides a find_free_slot() function but it does not work when
# reserving a vlan and using python3 (as of april 6, 2021).
# moreover, we need to verify that in the selected slot we have one node
# with two ethernet network interfaces to run the server.
def find_free_slot(recipe_info, vlan_type, slots, resources_wanted):
    # note:
    # <slot> = (<start_ts>, <end_ts>, <resources>)
    # <resources> = {
    #   <site|cluster|grid5000> : <number-of-nodes>,
    #   <kavlan> : [ <site1>, <site2>, ... ]
    #   ...
    # }
    # if reserving a local VLAN, <kavlan> value is an integer
    # instead of the list of sites.
    tip = None
    for slot in slots:
        if is_maintenance_slot(slot):
            continue
        if not slot_has_a_node_suitable_for_server(recipe_info, slot):
            tip = "select another site for walt server"
            continue
        if not slot_has_kavlan(slot):
            tip = "no kavlan available, retry later"
            continue
        if not slot_has_requested_nodes(slot, resources_wanted):
            tip = "select fewer nodes"
            continue
        return True, dict(
            resources_wanted=resources_wanted,
            vlan_type=vlan_type,
            selected_slot=dict(resources=slot[2], start=slot[0], end=slot[1]),
        )
    # Could not find a slot with requested resources in the whole
    # planning. Return a help tip by considering what was still
    # missing on the last slot (the most distant slot in time).
    return False, dict(tip=tip)


def append_site_resource(site_resources, site, resource):
    if site in site_resources:
        site_resources[site].append(resource)
    else:
        site_resources[site] = [resource]


SERVER_NODE_RESOURCE = """{eth_count>1}/nodes=1"""
VLAN_RESOURCE = """{type='%s'}/vlan=1"""
JOB_NAME = "WALT"


def get_helper_command(deployment_id):
    # notes:
    # * the program specified with '-p' option will be called on one of the sites
    #   where jobs are run, which may not be this current site where walt command
    #   is run. So we have to connect back to this site to run walt-g5k-deploy-helper.
    # * walt may have been installed in a virtualenv, so we must ensure the current
    #   python interpreter is reused to run the helper program (otherwise, if run
    #   with the default python interpreter of the OS, the helper may fail because
    #   of unavailable python dependencies, or usage of an old interpreter).
    current_site = get_local_g5k_site()
    helper_path = shutil.which("walt-g5k-deploy-helper")
    helper_python_exe = sys.executable
    return f"ssh {current_site} {helper_python_exe} {helper_path} {deployment_id}"


def get_job_logs_dir(deployment_id):
    return f"{str(Path.home())}/.walt-g5k/deployments/{deployment_id}/logs"


def walltime_as_seconds(wt):
    elems = tuple(int(e) for e in wt.split(":"))
    elems += (0,) * (3 - len(elems))
    hours, minutes, seconds = elems
    return hours * 3600 + minutes * 60 + seconds


def select_vlan_site(recipe_info, sites):
    # compute the set of involved sites (for the server and / or the nodes)
    involved_sites = set(
        [recipe_info["server"]["site"]] + list(recipe_info["node_counts"].keys())
    )
    # sort given input sites, involved sites last if any
    sorted_sites = sorted(sites, key=lambda site: (site in involved_sites))
    # preferably reserve the global vlan in a site already involved
    # (otherwise we will have to manage one more job just for this vlan)
    return sorted_sites[-1]


def get_submission_info(recipe_info, deployment_id, start_time_margin):
    result, info = analyse_reservation(recipe_info, start_time_margin)
    if result is False:
        return False, info
    server_site = recipe_info["server"]["site"]
    walltime = recipe_info["walltime"]
    vlan_type = info["vlan_type"]
    if vlan_type == "kavlan-local":
        vlan_site = server_site
    else:  # kavlan-global
        # use one of the sites which have their global vlan free in the selected slot
        vlan_site = select_vlan_site(
            recipe_info, info["selected_slot"]["resources"]["kavlan"]
        )
    reservation_date = info["selected_slot"]["start"]
    logs_dir = get_job_logs_dir(deployment_id)
    deployment_info = {
        "vlan": {"type": vlan_type, "site": vlan_site},
        "start_date": reservation_date,
        "end_date": reservation_date + walltime_as_seconds(walltime),
        "sites": {},
        "logs_dir": logs_dir,
        **recipe_info,
    }
    deployment_info["server"]["g5k_env_file"] = WALT_SERVER_ENV_FILE
    site_resources = {}
    for site, node_count in recipe_info["node_counts"].items():
        if node_count > 0:
            resource = "/nodes=" + str(node_count)
            append_site_resource(site_resources, site, resource)
    append_site_resource(site_resources, server_site, SERVER_NODE_RESOURCE)
    append_site_resource(site_resources, vlan_site, VLAN_RESOURCE % vlan_type)
    oar_date = datetime.fromtimestamp(reservation_date).strftime("%Y-%m-%d %H:%M:%S")
    for site, resources in site_resources.items():
        site_resources = "+".join(resources)
        site_resources += ",walltime=" + walltime
        cmd_args = ["oarsub", "-r", oar_date, "-l", site_resources, "-t", "deploy"]
        if site == server_site:
            helper_cmd = get_helper_command(deployment_id)
            if DEBUG_MODE:
                print("DEBUG_MODE: the following command should be run manually.")
                print(helper_cmd)
            else:
                # Job logs should be redirected to the front-end running the walt client
                # by a proper redirection of standard streams as part of helper startup
                # code.
                # For debugging purpose (if this helper code is broken), we also save
                # stdout & stderr of the job by using proper oarsub options.
                # Note that these logs will be found on the site frontend running the
                # main job (i.e., the site running the walt server) which may not be
                # the one running the walt client.
                # Since these are saved mostly for debugging, we hide them ('.' prefix).
                local_stdout = f"{logs_dir}/.local.deploy.stdout"
                local_stderr = f"{logs_dir}/.local.deploy.stderr"
                cmd_args += ["-O", local_stdout, "-E", local_stderr, helper_cmd]
        deployment_info["sites"][site] = {"submit_args": cmd_args}
    return True, deployment_info
