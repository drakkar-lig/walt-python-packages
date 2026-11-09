import sys
from pathlib import Path

# Run the tests against the source tree, not against an installed
# walt-server package (if any).  'walt' is a pkgutil-style namespace
# package, so 'walt.common' is found in the 'common' directory.
REPO_ROOT = Path(__file__).resolve().parents[2]
for pkg_dir in ("common", "server"):
    sys.path.insert(0, str(REPO_ROOT / pkg_dir))
