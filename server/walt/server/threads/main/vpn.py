import tempfile, sys
from pathlib import Path
from time import time
from collections import defaultdict
from pkg_resources import resource_string
from walt.common.tools import do, chown_tree
from walt.common.constants import UNSECURE_ECDSA_KEYPAIR

# Walt VPN clients should first connect with our unsecure key pair (written below).
# They will be forcibly directed to "walt-vpn-auth-tool" command.
# This command connects to walt-server-daemon and asks for generation of VPN client
# credentials.
# If someone has been running "walt vpn monitor" when this happened, he can accept
# or deny the request. Otherwise the request is immediately denied (except in a
# specific case, see below).
# If the request is accepted, "walt-vpn-auth-tool" dumps new credential information
# on its output. Thus, the VPN client receives this information on the other side
# of the ssh channel and can automatically set it up.
# After this first step has been done, the client will use this new credentials to
# connect to the VPN.

# "walt vpn monitor" is run in a loop in order to easily accept a batch of access
# requests. It first calls API function wait_grant_request(). When a device requests
# VPN access, wait_grant_request() is unblocked and the "walt vpn monitor" command
# prompts the request to the user. When the user answers, its response is transmitted
# to the server using API function respond_grant_request(), and the device request
# is unblocked with an appropriate result. Then, "walt vpn monitor" restarts its loop
# and calls API function wait_grant_request() again, waiting for next device request.
# However, if the user does not respond immediately to a given request, another device may
# try to request a grant at this time. Since the "walt vpn monitor" loop is blocked on
# user input, the server has no pending wait_grant_request(). Because of this,
# we record the fact a given device request is pending user response. And, for a short
# period of time, we allow any other device request to wait for "walt vpn monitor" to
# loop again and respond to this new request.

WALT_VPN_USER = dict(
    home_dir = Path("/var/lib/walt/vpn"),
    authorized_keys_pattern = """
# walt VPN secured access
cert-authority,restrict,command="walt-vpn-endpoint" %(ca_pub_key)s
# walt VPN authentication step
restrict,command="walt-vpn-auth-tool $SSH_ORIGINAL_COMMAND" %(unsecure_pub_key)s
""")

VPN_CA_KEY = WALT_VPN_USER['home_dir'] / '.ssh' / 'vpn-ca-key'
VPN_CA_KEY_PUB = WALT_VPN_USER['home_dir'] / '.ssh' / 'vpn-ca-key.pub'

UNSECURE_KEY, UNSECURE_KEY_PUB = UNSECURE_ECDSA_KEYPAIR['openssh-priv'], UNSECURE_ECDSA_KEYPAIR['openssh-pub']

PENDING_USER_RESPONSE_DELAY = 5*60  # seconds

WAITING = 0
PENDING_USER_RESPONSE = 1

class VPNManager:
    def __init__(self):
        self.waiting_requests = {}
        self.waiting_monitors = set()
        self.verify_conf()

    # when a user types "walt vpn monitor", we get here
    def wait_grant_request(self, task):
        self.cleanup()
        # check if another device was waiting for this "walt vpn monitor" to loop again.
        for device_mac, request_task_info in self.waiting_requests.items():
            if request_task_info['status'] == WAITING:
                # yes, immediately indicate to "walt vpn monitor" that it should respond
                # the request of this device (by returning its mac),
                # and update the device request task status.
                request_task_info['status'] = PENDING_USER_RESPONSE
                request_task_info['timeout'] = time() + PENDING_USER_RESPONSE_DELAY
                return device_mac
        # otherwise, there is no device request pending
        task.set_async()   # result will be available later
        self.waiting_monitors.add(task)

    # cleanup disconnected tasks and those which timed out
    def cleanup(self):
        for mac, task_info in self.waiting_requests.copy().items():
            task = task_info['task']
            if not task.is_alive():
                del self.waiting_requests[mac]
                continue
            if task_info['timeout'] < time():
                task.return_result(('FAILED', "Timed out waiting for user response!"))
                del self.waiting_requests[mac]
                continue
        for task in self.waiting_monitors.copy():
            if not task.is_alive():
                self.waiting_monitors.remove(task)

    # check if some of the current "walt vpn monitor" commands are waiting for user input.
    def have_pending_user_responses(self):
        for request_task_info in self.waiting_requests.values():
            if request_task_info['status'] == PENDING_USER_RESPONSE:
                return True
        return False

    # a device requesting VPN access grant will call this method.
    def request_grant(self, task, device_mac):
        print('vpn grant request', device_mac)
        self.cleanup()
        if len(self.waiting_monitors) == 0 and not self.have_pending_user_responses():
            return ('FAILED', "No pending 'walt vpn monitor' command.")
        task.set_async()   # result will be available later
        if len(self.waiting_monitors) > 0:
            task_status = PENDING_USER_RESPONSE
            for monitor_task in self.waiting_monitors:
                monitor_task.return_result(device_mac)
            self.waiting_monitors = set()
        else:   # some monitors are there but not connected
                # (waiting for user response about another device)
            task_status = WAITING
        timeout = time() + PENDING_USER_RESPONSE_DELAY
        self.waiting_requests[device_mac] = {
                    'task': task,
                    'status': task_status,
                    'timeout': timeout,
        }

    # "walt vpn monitor" calls this function to transmit user's response about a device request.
    def respond_grant_request(self, device_mac, auth_ok):
        request_task_info = self.waiting_requests.get(device_mac, None)
        if request_task_info is None:
            return ('FAILED', "No such device (it may have been processed by another 'walt vpn monitor' command).")
        request_task = request_task_info['task']
        if auth_ok:
            keypair = self.generate_device_keys(device_mac)
            request_task.return_result(('OK',) + keypair)
            result = ('OK', 'Device access was granted.')
        else:
            request_task.return_result(('FAILED', "Denied!"))
            result = ('OK', 'Device access was denied.')
        self.waiting_requests.pop(device_mac)
        return result

    def verify_conf(self):
        home_dir = WALT_VPN_USER['home_dir']
        if not home_dir.exists():     # if not configured
            # create user walt-vpn
            home_dir = WALT_VPN_USER['home_dir']
            do("useradd -U -d %(home_dir)s walt-vpn" % dict(
                home_dir = str(home_dir)
            ))
            # generate VPN CA key
            VPN_CA_KEY.parent.mkdir(parents=True)
            do("ssh-keygen -N '' -t ecdsa -b 521 -f %s" % str(VPN_CA_KEY))
            ca_pub_key = VPN_CA_KEY_PUB.read_text().strip()
            # create appropriate authorized_keys file
            authorized_keys_file = home_dir / '.ssh' / 'authorized_keys'
            authorized_keys_file.write_text(
                WALT_VPN_USER['authorized_keys_pattern'] % dict(
                ca_pub_key = ca_pub_key,
                unsecure_pub_key = UNSECURE_KEY_PUB
            ))
            # fix owner to 'walt-vpn'
            chown_tree(home_dir, 'walt-vpn', 'walt-vpn')

    def generate_device_keys(self, device_mac):
        device_id = 'vpn_' + device_mac.replace(':', '')
        with tempfile.TemporaryDirectory() as tmpdirname:
            do("ssh-keygen -C %(comment)s -N '' -t ecdsa -b 384 -f %(tmpdir)s/key" % dict(
                    comment = 'walt-vpn@' + device_id,
                    tmpdir = tmpdirname
            ))
            do("ssh-keygen -s %(vpn_ca_key)s -I '%(device_id)s' -n %(principal)s %(tmpdir)s/key.pub" % dict(
                    vpn_ca_key = str(VPN_CA_KEY),
                    device_id = device_id,
                    principal = 'walt-vpn',
                    tmpdir = tmpdirname
            ))
            tmpdir = Path(tmpdirname)
            priv_key = (tmpdir / 'key').read_text()
            pub_cert_key = (tmpdir / 'key-cert.pub').read_text()
            return (priv_key, pub_cert_key)

    def get_unsecure_key_pair(self):
        return (UNSECURE_KEY, UNSECURE_KEY_PUB)

    def get_vpn_proxy_setup_script(self):
        script_content = resource_string(__name__, "vpn-proxy-setup.sh").decode(sys.getdefaultencoding())
        return script_content % dict(
            ca_pub_key = VPN_CA_KEY_PUB.read_text().strip(),
            unsecure_pub_key = UNSECURE_KEY_PUB
        )
