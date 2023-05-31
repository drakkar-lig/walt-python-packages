import sys

from podman import PodmanClient

PODMAN_API_SOCKET = "unix:///run/walt/podman/podman.socket"
USAGE = """\
Usage:  $ walt-image-check <image-name-or-id>
"""


def run():
    if len(sys.argv) != 2:
        print(USAGE)
        sys.exit(2)
    image_name = sys.argv[1]
    p = PodmanClient(base_url=PODMAN_API_SOCKET)
    data = p.images.get_registry_data(image_name)
    labels = data.attrs["Labels"]
    node_models = []
    if labels is not None:
        node_models = labels["walt.node.models"].split(",")
    if len(node_models) == 0:
        sys.stderr.write(
            "FAILED: The image is missing a 'LABEL walt.node.models=<models>' to"
            " indicate compatibility.\n"
        )
        sys.exit(1)
    sys.stdout.write("OK\n")


if __name__ == "__main__":
    run()
