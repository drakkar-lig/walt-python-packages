import datetime, cPickle as pickle

from walt.common.crypto.dh import DHPeer
from walt.common.api import api, api_expose_method
from walt.common.tools import serialize_ordered_dict, deserialize_ordered_dict

from walt.server.threads.main.apisession import APISession

# Client -> Server API (thus the name CSAPI)
# Provides remote calls performed from a client to the server.

@api
class CSAPI(APISession):

    @api_expose_method
    def device_rescan(self, context, device_set):
        context.server.device_rescan(context.requester.sync, context.remote_ip, device_set)

    @api_expose_method
    def device_tree(self, context, show_all):
        return context.topology.tree(context.requester.sync, show_all)

    @api_expose_method
    def device_show(self, context):
        return context.devices.show()

    @api_expose_method
    def show_nodes(self, context, username, show_all):
        return context.nodes.show(username, show_all)

    @api_expose_method
    def create_vnode(self, context, node_name):
        return context.server.create_vnode(context.requester.sync, node_name)

    @api_expose_method
    def remove_vnode(self, context, node_name):
        return context.server.remove_vnode(context.requester.sync, node_name)

    @api_expose_method
    def prepare_ssh_access(self, context, node_set):
        return context.nodes.prepare_ssh_access(context.requester.sync, node_set)

    @api_expose_method
    def get_nodes_ip(self, context, node_set):
        return context.nodes.get_nodes_ip(context.requester.sync, node_set)

    @api_expose_method
    def get_device_ip(self, context, device_name):
        return context.devices.get_device_ip(
                        context.requester.sync, device_name)

    @api_expose_method
    def get_node_ip(self, context, node_name):
        return context.nodes.get_node_ip(
                        context.requester.sync, node_name)

    @api_expose_method
    def blink(self, context, node_name, blink_status):
        return context.nodes.blink(context.requester.sync, node_name, blink_status)

    @api_expose_method
    def parse_set_of_nodes(self, context, node_set):
        nodes = context.nodes.parse_node_set(context.requester.sync, node_set)
        if nodes:
            return tuple(n.name for n in nodes)

    @api_expose_method
    def includes_devices_not_owned(self, context, device_set, warn):
        return context.devices.includes_devices_not_owned(context.requester.sync, device_set, warn)

    @api_expose_method
    def develop_node_set(self, context, node_set):
        return context.nodes.develop_node_set(context.requester.sync, node_set)

    @api_expose_method
    def develop_device_set(self, context, device_set):
        return context.devices.develop_device_set(context.requester.sync, device_set)

    @api_expose_method
    def poweroff(self, context, node_set, warn_poe_issues):
        return context.nodes.setpower(context.requester.sync, node_set, False, warn_poe_issues)

    @api_expose_method
    def poweron(self, context, node_set, warn_poe_issues):
        return context.nodes.setpower(context.requester.sync, node_set, True, warn_poe_issues)

    @api_expose_method
    def softreboot(self, context, node_set, hide_issues):
        return context.nodes.softreboot(context.requester.sync, node_set, hide_issues)

    @api_expose_method
    def virtual_or_physical(self, context, node_set):
        return context.nodes.virtual_or_physical(context.requester.sync, node_set)

    @api_expose_method
    def hard_reboot_vnodes(self, context, node_set):
        return context.nodes.hard_reboot_vnodes(context.requester.sync, node_set)

    @api_expose_method
    def validate_node_cp(self, context, src, dst):
        return context.nodes.validate_cp(context.requester.sync, src, dst)

    @api_expose_method
    def wait_for_nodes(self, context, node_set):
        context.nodes.wait(context.requester.sync, context.task, node_set)

    @api_expose_method
    def rename(self, context, old_name, new_name):
        context.server.rename_device(context.requester.sync, old_name, new_name)

    @api_expose_method
    def has_image(self, context, image_name):
        return context.images.has_image(context.requester.sync, image_name)

    @api_expose_method
    def set_image(self, context, node_set, image_name):
        return context.server.set_image(context.requester.sync, node_set, image_name)

    @api_expose_method
    def count_logs(self, context, **kwargs):
        return context.server.count_logs(**kwargs)

    @api_expose_method
    def forget(self, context, device_name):
        context.server.forget_device(device_name)

    @api_expose_method
    def get_device_info(self, context, device_name):
        device_info = context.devices.get_device_info(context.requester.sync, device_name)
        return serialize_ordered_dict(device_info._asdict())

    @api_expose_method
    def apply_switch_conf(self, context, device_name, conf):
        conf = deserialize_ordered_dict(conf)
        return context.devices.apply_switch_conf(context.requester.sync, device_name, conf)

    @api_expose_method
    def fix_image_owner(self, context, other_user):
        return context.images.fix_owner(context.requester.sync, other_user)

    @api_expose_method
    def search_images(self, context, keyword, tty_mode=False):
        context.images.search(context.requester.sync, context.task, keyword, tty_mode)

    @api_expose_method
    def clone_image(self, context, clonable_link, force=False):
        context.images.clone(requester = context.requester.sync,
                          task = context.task,
                          clonable_link = clonable_link,
                          force = force)

    @api_expose_method
    def create_dh_peer(self, context):
        dh_peer = DHPeer()
        dh_peer_id = self.register_session_object(dh_peer)
        return dh_peer_id, dh_peer.pub_key

    @api_expose_method
    def establish_dh_session(self, context, dh_peer_id, client_pub_key):
        dh_peer = self.get_session_object(dh_peer_id)
        dh_peer.establish_session(client_pub_key)

    @api_expose_method
    def publish_image(self, context, auth_conf, image_name):
        dh_peer = self.get_session_object(auth_conf['dh_peer_id'])
        context.images.publish(requester = context.requester.sync,
                          task = context.task,
                          dh_peer = dh_peer,
                          auth_conf = auth_conf,
                          image_name = image_name)

    @api_expose_method
    def docker_login(self, context, auth_conf):
        dh_peer = self.get_session_object(auth_conf['dh_peer_id'])
        return context.server.docker.hub.login(dh_peer, auth_conf, context.requester.sync)

    @api_expose_method
    def show_images(self, context, refresh):
        return context.images.show(context.requester.sync, refresh)

    @api_expose_method
    def create_image_shell_session(self, context, image_name, task_label):
        session = context.images.create_shell_session(
                    context.requester.sync, image_name, task_label)
        if session == None:
            return None
        session_id = self.register_session_object(session)
        fullname, container_name, default_new_name = session.get_parameters()
        return session_id, fullname, container_name, default_new_name

    @api_expose_method
    def image_shell_session_save(self, context, session_id, new_name, name_confirmed):
        session = self.get_session_object(session_id)
        return context.server.image_shell_session_save(
                    context.requester.sync, session, new_name, name_confirmed)

    @api_expose_method
    def remove_image(self, context, image_name):
        context.images.remove(context.requester.sync, image_name)

    @api_expose_method
    def rename_image(self, context, image_name, new_name):
        context.images.rename(context.requester.sync, image_name, new_name)

    @api_expose_method
    def duplicate_image(self, context, image_name, new_name):
        context.images.duplicate(context.requester.sync, image_name, new_name)

    @api_expose_method
    def validate_image_cp(self, context, src, dst):
        return context.images.validate_cp(context.requester.sync, src, dst)

    @api_expose_method
    def add_checkpoint(self, context, cp_name, pickled_date):
        date = None
        if pickled_date:
            date = pickle.loads(pickled_date)
        context.logs.add_checkpoint(context.requester.sync, cp_name, date)

    @api_expose_method
    def remove_checkpoint(self, context, cp_name):
        context.logs.remove_checkpoint(context.requester.sync, cp_name)

    @api_expose_method
    def list_checkpoints(self, context):
        context.logs.list_checkpoints(context.requester.sync)

    @api_expose_method
    def get_pickled_time(self, context):
        return pickle.dumps(datetime.datetime.now())

    @api_expose_method
    def get_pickled_checkpoint_time(self, context, cp_name):
        return context.logs.get_pickled_checkpoint_time(context.requester.sync, cp_name)

    @api_expose_method
    def update_hub_metadata(self, context, auth_conf, waltplatform_user):
        dh_peer = self.get_session_object(auth_conf['dh_peer_id'])
        context.images.update_hub_metadata(context, auth_conf, dh_peer, waltplatform_user)

    @api_expose_method
    def set_device_config(self, context, device_set, conf_args):
        context.server.settings.set_device_config(context.requester.sync, device_set, conf_args)
        context.server.dhcpd.update()
