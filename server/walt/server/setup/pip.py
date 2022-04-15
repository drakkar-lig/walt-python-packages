import requests, subprocess

GET_PIP_URL         = "https://bootstrap.pypa.io/get-pip.py"

def install_pip():
    resp = requests.get(GET_PIP_URL)
    if not resp.ok:
        raise Exception(f'Failed to fetch {GET_PIP_URL}: {resp.reason}')
    subprocess.run(['python3', '-'], input=resp.content, capture_output=True, check=True)

class pip:
    @staticmethod
    def install(packages_spec):
        subprocess.run(f'pip3 install --upgrade {packages_spec}'.split(),
                   capture_output=True, check=True)
