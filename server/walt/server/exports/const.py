from pathlib import Path

TFTP_ROOT = Path("/var/lib/walt")
PXE_PATH = TFTP_ROOT / "pxe"
NODES_PATH = TFTP_ROOT / "nodes"
TFTP_STATIC_DIR = TFTP_ROOT / "tftp-static"
TFTP_STATIC_DIR_TS = 1741598952
NODE_PROBING_PATH = NODES_PATH / 'probing'
NODE_PROBING_TFTP_PATH = NODE_PROBING_PATH / 'tftp'
EXPORTS_STATUS_PATH = TFTP_ROOT / "status.pickle"
MOUNT_DEADLINES_PATH = TFTP_ROOT / "deadlines.db"
OBSOLETE_TFTP_STANDBY_PATH = TFTP_ROOT / "tftp-standby"
OBSOLETE_PERSIST_EXPORTS_PATH = Path("/etc/exports.d/walt-persist.exports")
