import os
import time


# execo provides this function but it does not work fine
# with python3 (as of april 6, 2021)
def oar_datetime_to_unixts(dt):
    """Convert a naive g5k datetime to a unix timestamp.

    Input datetime is expected to be naive (no tz attached) and
    to reflect the time  in the g5k oar/oargrid timezone Europe/Paris."""
    from execo.time_utils import datetime_to_unixts

    # forking code because modifying os.environ["TZ"] and calling
    # time.tzset() is not thread-safe
    rend, wend = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.environ["TZ"] = "Europe/Paris"
        time.tzset()
        ts = datetime_to_unixts(dt)
        os.write(wend, str(ts).encode("ascii"))
        os._exit(0)
    else:
        os.close(wend)
        f = os.fdopen(rend)
        ts = float(f.read())
        f.close()
        os.waitpid(pid, 0)
        return ts


# execo provides this function but it filters out local vlans,
# and in our case we need them.
def _get_vlans_API(site):
    """Retrieve the list of VLAN of a site from the 3.0 Grid'5000 API"""
    from execo_g5k.api_utils import get_resource_attributes

    equips = get_resource_attributes("/sites/" + site + "/network_equipments/")
    vlans = []
    for equip in equips["items"]:
        if "vlans" in equip and len(equip["vlans"]) > 2:
            for params in equip["vlans"].values():
                if isinstance(params, dict) and "name" in params:
                    vlans.append(params["name"])
    return vlans


def load_execo_g5k():
    import logging
    # execo has two methods for loading the planning: API or OAR database.
    # it uses the OAR database if it is able to import the module psycopg2,
    # and the API otherwise. The above trick to allow local vlans only
    # applies to the API access, and hacking the database access would require
    # more code, so we prevent the loading of psycopg2 to force the API method.
    import sys
    sys.modules['psycopg2'] = None

    from execo.log import logger

    logger.setLevel(logging.WARNING)
    import execo_g5k.api_utils
    import execo_g5k.charter
    import execo_g5k.oargrid
    import execo_g5k.planning

    # redirect to our fixed function(s)
    execo_g5k.charter.oar_datetime_to_unixts = oar_datetime_to_unixts
    execo_g5k.planning._get_vlans_API = _get_vlans_API
    return execo_g5k
