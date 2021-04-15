import os, time

# execo provides this function but it does not work fine
# with python3 (as of april 6, 2021)
def oar_datetime_to_unixts(dt):
    """Convert a naive datetime (no tz attached) in the g5k oar/oargrid timezone Europe/Paris to a unix timestamp."""
    from execo.time_utils import datetime_to_unixts
    # forking code because modifying os.environ["TZ"] and calling
    # time.tzset() is not thread-safe
    rend, wend = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.environ["TZ"] = "Europe/Paris"
        time.tzset()
        ts = datetime_to_unixts(dt)
        os.write(wend, str(ts).encode('ascii'))
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
    equips = get_resource_attributes('/sites/'+site+'/network_equipments/')
    vlans = []
    for equip in equips['items']:
        if 'vlans' in equip and len(equip['vlans']) >2:
            for params in equip['vlans'].values():
                if type( params ) == type({}) and 'name' in params:
                    vlans.append(params['name'])
    return vlans

def load_execo_g5k():
    import logging
    from execo.log import logger
    logger.setLevel(logging.WARNING)
    import execo_g5k.planning, execo_g5k.oargrid, \
           execo_g5k.charter, execo_g5k.api_utils
    # redirect to our fixed function(s)
    execo_g5k.charter.oar_datetime_to_unixts = oar_datetime_to_unixts
    execo_g5k.planning._get_vlans_API = _get_vlans_API
    return execo_g5k