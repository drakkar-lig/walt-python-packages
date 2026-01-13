import numpy as np

from walt.server.tools import (
        get_rpi_foundation_mac_vendor_ids,
        get_server_ip,
        get_walt_subnet,
)

WALT_SUBNET = get_walt_subnet()
WALT_SERVER_IP = get_server_ip()

RPI_MAC_CONDITION = " or ".join(
        f"""d.mac like '{vendor_id}:%'""" \
        for vendor_id in get_rpi_foundation_mac_vendor_ids())

QUERY_EXPORTS_INFO = f"""
SELECT d.mac, d.ip, d.name, d.type,
  n.model, n.image,
  split_part(n.image, '/', 1)
    as owner,
  REPLACE(d.mac, ':', '-')
    as mac_dash,
  COALESCE((d.conf->'mount.persist')::bool, true)
    as mount_persist,
  COALESCE(d.conf->>'boot.mode', 'network-volatile')
    as boot_mode,
  ({RPI_MAC_CONDITION})
    as is_rpi,
  NULL
    as image_id,
  NULL
    as image_size_kib
FROM devices d
LEFT JOIN nodes n ON d.mac = n.mac
WHERE d.ip IS NOT NULL
  AND d.ip::inet << '{str(WALT_SUBNET)}'::cidr
"""


class FilesystemsExporter:
    def __init__(self, server):
        self.db = server.db
        self.registry = server.registry
        self.ev_loop = server.ev_loop

    def get_exports_info(self):
        db_devices = self.db.execute(QUERY_EXPORTS_INFO)
        # extract nodes, retrieve their image_id and image size
        nodes_mask = (db_devices.type == 'node')
        db_nodes = db_devices[nodes_mask]
        metadata = self.registry.get_multiple_metadata(db_nodes.image)
        image_ids = np.fromiter((m["image_id"] for m in metadata), object)
        db_nodes.image_id[:] = image_ids
        image_sizes = np.fromiter((m["size_kib"] for m in metadata), object)
        db_nodes.image_size_kib[:] = image_sizes
        # compute rpi devices of type "unknown"
        unknown_rpis_mask = (db_devices.type == 'unknown')
        unknown_rpis_mask &= db_devices.is_rpi.astype(bool)
        unknown_rpis = db_devices[unknown_rpis_mask]
        # compute free IPs
        free_ips = set(str(ip) for ip in WALT_SUBNET.hosts())
        free_ips.discard(WALT_SERVER_IP)
        free_ips -= set(db_devices.ip)
        free_ips = np.array(list(free_ips), dtype=object)
        return db_nodes, unknown_rpis, free_ips

    def wf_prepare(self, wf, **env):
        self.ev_loop.wf_do(wf, "walt-exports-prepare", silent=False)

    def plan_update(self, next_time):
        self.ev_loop.plan_event(
            ts=next_time, callback=self.trigger_update
        )

    def trigger_update(self):
        self.ev_loop.do("walt-exports-update --auto-recall", silent=False)

    def wf_update(self, wf, **env):
        self.ev_loop.wf_do(wf, "walt-exports-update --auto-recall",
                           silent=False)

    def cleanup(self):
        self.ev_loop.do("walt-exports-cleanup", silent=False)
