from time import time

from walt.common.api import api, api_expose_method
from walt.common.tools import format_image_fullname
from walt.server.processes.main.apisession import APISession
from walt.server.processes.main.images.image import validate_image_name
from walt.server.tools import np_record_to_dict, np_recarray_to_tuple_of_dicts

# Client -> Server API (thus the name CSAPI)
# Provides remote calls performed from a client to the server.


@api
class CSAPI(APISession):
    @api_expose_method
    def device_rescan(self, context, device_set):
        context.server.device_rescan(
            context.requester, context.task, device_set
        )

    @api_expose_method
    def device_tree(self, context, show_all):
        context.task.set_async()
        return context.blocking.topology_tree(
            context.requester, context.task.return_result, show_all
        )

    @api_expose_method
    def device_show(self, context):
        return context.devices.show()

    @api_expose_method
    def show_nodes(self, context, username, show_all, names_only=False):
        return context.nodes.show(username, show_all, names_only)

    @api_expose_method
    def show_images(self, context, **kwargs):
        return context.images.show(context.requester, **kwargs)

    @api_expose_method
    def create_vnode(self, context, node_name):
        return context.server.create_vnode(context.requester, context.task, node_name)

    @api_expose_method
    def remove_vnode(self, context, node_name):
        return context.server.remove_vnode(context.requester, context.task, node_name)

    @api_expose_method
    def get_nodes_ip(self, context, node_set):
        return context.nodes.get_nodes_ip(context.requester, node_set)

    @api_expose_method
    def get_nodes_info(self, context, node_set):
        return np_recarray_to_tuple_of_dicts(
            context.nodes.get_nodes_info(context.requester, node_set)
        )

    @api_expose_method
    def get_device_ip(self, context, device_name):
        return context.devices.get_device_ip(context.requester, device_name)

    @api_expose_method
    def get_node_ip(self, context, node_name):
        return context.nodes.get_node_ip(context.requester, node_name)

    @api_expose_method
    def blink(self, context, node_name, blink_status):
        return context.nodes.blink(
            context.requester, context.task, node_name, blink_status
        )

    @api_expose_method
    def vnode_console_input(self, context, node_mac, buf):
        context.nodes.vnode_console_input(node_mac, buf)

    @api_expose_method
    def parse_set_of_nodes(self, context, node_set):
        nodes = context.nodes.parse_node_set(context.requester, node_set)
        if nodes is not None:
            return tuple(n.name for n in nodes)

    @api_expose_method
    def parse_set_of_devices(self, context, device_set, allowed_device_set=None):
        devices = context.devices.parse_device_set(
            context.requester, device_set, allowed_device_set=allowed_device_set
        )
        if devices is not None:
            return tuple(d.name for d in devices)

    @api_expose_method
    def filter_ownership(self, context, node_set):
        return context.nodes.filter_ownership(context.requester, node_set)

    @api_expose_method
    def develop_node_set(self, context, node_set):
        return context.nodes.develop_node_set(context.requester, node_set)

    @api_expose_method
    def develop_device_set(self, context, device_set):
        return context.devices.develop_device_set(context.requester, device_set)

    @api_expose_method
    def reboot_nodes(self, context, node_set,
                     hard_only=False, cause="reboot requested"):
        return context.nodes.reboot_node_set(
            context.requester, context.task, node_set, hard_only, cause
        )

    @api_expose_method
    def validate_node_cp(self, context, src, dst):
        return context.server.validate_cp(
                context.task, context.requester, "node", src, dst)

    @api_expose_method
    def node_cp_to_booted_image(self, context, node_name, **path_info):
        return context.server.node_cp_to_booted_image(
            context.requester, context.task, self, node_name, **path_info
        )

    @api_expose_method
    def wait_for_nodes(self, context, node_set):
        return context.nodes.wait(context.requester, context.task, node_set)

    @api_expose_method
    def rename(self, context, old_name, new_name):
        return context.server.rename_device(context.requester, old_name, new_name)

    @api_expose_method
    def has_image(self, context, image_name, default_allowed):
        return context.images.has_image(context.requester, image_name, default_allowed)

    @api_expose_method
    def set_image(self, context, node_set, image_name):
        return context.server.set_image(context.requester, node_set, image_name)

    @api_expose_method
    def count_logs(self, context, **kwargs):
        return context.server.db.count_logs(**kwargs)

    @api_expose_method
    def forget(self, context, device_name):
        return context.server.forget_device(
            context.requester, context.task, device_name
        )

    @api_expose_method
    def get_device_info(self, context, device_name):
        device_info = context.devices.get_device_info(context.requester, device_name)
        if device_info is None:
            return None
        return np_record_to_dict(device_info)

    @api_expose_method
    def fix_image_owner(self, context, other_user):
        return context.images.fix_owner(context.requester, other_user)

    @api_expose_method
    def search_images(self, context, keyword, tty_mode=None):
        context.images.search(context.requester, context.task, keyword, tty_mode)

    @api_expose_method
    def clone_image(self, context, clonable_link, force=False, image_name=None):
        context.images.clone(
            requester=context.requester,
            server=context.server,
            task=context.task,
            clonable_link=clonable_link,
            force=force,
            image_name=image_name,
        )

    @api_expose_method
    def publish_image(self, context, registry_label, image_name):
        return context.images.publish(
            requester=context.requester,
            task=context.task,
            registry_label=registry_label,
            image_name=image_name,
        )

    @api_expose_method
    def registry_login(self, context, reg_name):
        context.task.set_async()
        return context.blocking.registry_login(
            context.requester, context.task.return_result, reg_name
        )

    @api_expose_method
    def get_images_tabular_data(self, context, username, refresh, fields=None):
        # clients running "api.images.get_images()" call this,
        # and they may not have numpy, so use to_list() to convert to a list
        # of tuples.
        return context.images.get_user_tabular_data(
            context.requester, username, refresh, fields
        ).tolist()

    @api_expose_method
    def create_image_shell_session(self, context, image_name, task_label):
        session = context.images.create_shell_session(
            context.requester, image_name, task_label
        )
        if session is None:
            return None
        session_id = self.register_session_object(session)
        fullname, container_name, default_new_name = session.get_parameters()
        return session_id, fullname, container_name, default_new_name

    @api_expose_method
    def image_shell_session_save(
        self, context, username, session_id, new_name, name_confirmed
    ):
        session = self.get_session_object(session_id)
        # verify name syntax
        if not validate_image_name(context.requester, new_name):
            return "NAME_NOT_OK"
        image_fullname = format_image_fullname(username, new_name)
        context.task.set_async()
        return context.server.image_shell_session_save(
            context.requester,
            context.task.return_result,
            session,
            image_fullname,
            name_confirmed,
        )

    @api_expose_method
    def remove_image(self, context, image_name):
        return context.images.remove(context.requester, image_name)

    @api_expose_method
    def rename_image(self, context, image_name, new_name):
        return context.images.rename(context.requester, image_name, new_name)

    @api_expose_method
    def duplicate_image(self, context, image_name, new_name):
        return context.images.duplicate(context.requester, image_name, new_name)

    @api_expose_method
    def update_default_images(self, context):
        return context.images.update_default_images(context.requester, context.task)

    @api_expose_method
    def validate_image_cp(self, context, src, dst):
        return context.server.validate_cp(context.task,
                context.requester, "image", src, dst)

    @api_expose_method
    def squash_image(self, context, image_name, confirmed):
        return context.server.squash_image(
            requester=context.requester,
            task=context.task,
            image_name=image_name,
            confirmed=confirmed,
        )

    @api_expose_method
    def add_checkpoint(self, context, cp_name, date):
        context.logs.add_checkpoint(context.requester, cp_name, date)

    @api_expose_method
    def remove_checkpoint(self, context, cp_name):
        context.logs.remove_checkpoint(context.requester, cp_name)

    @api_expose_method
    def list_checkpoints(self, context):
        context.logs.list_checkpoints(context.requester)

    @api_expose_method
    def get_time(self, context):
        return time()

    @api_expose_method
    def get_checkpoint_time(self, context, cp_name):
        return context.logs.get_checkpoint_time(context.requester, cp_name)

    @api_expose_method
    def update_hub_metadata(self, context, waltplatform_user):
        return context.images.update_hub_metadata(context, waltplatform_user)

    @api_expose_method
    def set_device_config(self, context, device_set, conf_args):
        context.server.settings.set_device_config(
            context.requester, device_set, conf_args
        )
        context.server.dhcpd.update()

    @api_expose_method
    def get_device_config(self, context, device_set):
        context.server.settings.get_device_config(context.requester, device_set)

    @api_expose_method
    def set_port_config(self, context, switch_name, port_id, configuration):
        context.server.port_settings.set_config(context.requester,
                switch_name, port_id, configuration)

    @api_expose_method
    def get_port_config(self, context, switch_name, port_id):
        context.server.port_settings.get_config(context.requester,
                switch_name, port_id)

    @api_expose_method
    def get_device_config_data(self, context, device_set):
        return np_recarray_to_tuple_of_dicts(
            context.server.settings.get_device_config_data(
                context.requester, device_set
        ))

    @api_expose_method
    def shell_autocomplete(self, context, username, argv, debug=False):
        return context.server.shell_autocomplete(
            context.task, context.requester, username, argv, debug=debug
        )

    @api_expose_method
    def get_registries(self, context):
        return context.server.get_registries()

    @api_expose_method
    def create_image_build_session(self, context, **info):
        session = context.images.create_build_session(context.requester, **info)
        if session is None:
            return None
        session_id = self.register_session_object(session)
        session_info = session.get_parameters()
        session_info.update(session_id=session_id)
        return session_info

    @api_expose_method
    def run_image_build_from_url(self, context, session_id):
        session = self.get_session_object(session_id)
        return session.run_image_build_from_url(context.requester, context.task)

    @api_expose_method
    def run_image_build_from_node_diff(self, context, session_id):
        session = self.get_session_object(session_id)
        return session.run_image_build_from_node_diff(
                context.requester, context.server, context.task)

    @api_expose_method
    def finalize_image_build_session(self, context, session_id):
        session = self.get_session_object(session_id)
        return session.finalize_image_build_session(
            context.requester, context.server, context.task
        )

    @api_expose_method
    def get_clones_of_default_images(self, context, node_set):
        return context.images.store.get_clones_of_default_images(
            context.requester, node_set
        )

    @api_expose_method
    def get_client_install_wheels(self, context):
        # note: this CS entry is used for client auto-updates when a
        # version mismatch is detected between the client and the server.
        # So, if ever it changes, maintaining backward compatibility is
        # mandatory!
        return context.server.get_client_install_wheels()
