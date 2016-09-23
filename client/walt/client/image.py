#!/usr/bin/env python
from plumbum import cli
from walt.common.apilink import ResponseQueue
from walt.client.link import ClientToServerLink
from walt.client.tools import confirm
from walt.client.interactive import run_image_shell_prompt
from walt.client.transfer import run_transfer_with_image
from walt.client.auth import get_auth_conf

class WalTImage(cli.Application):
    """management of WalT-nodes operating system images"""
    pass

@WalTImage.subcommand("search")
class WalTImageSearch(cli.Application):
    """search for remote WalT node OS images"""
    def main(self, keyword=None):
        with ClientToServerLink() as server_link:
            q = ResponseQueue()
            server_link.search_images(q, keyword)
            print server_link.wait_queue(q)

@WalTImage.subcommand("clone")
class WalTImageClone(cli.Application):
    """clone a remote image into your working set"""
    _force = False # default
    _auto_update = False # default
    def main(self, clonable_image_link):
        q = ResponseQueue()
        with ClientToServerLink() as server_link:
            server_link.clone_image(q, clonable_image_link, self._force, self._auto_update)
            server_link.wait_queue(q)
    @cli.autoswitch(help='do it, even if it overwrites an existing image.')
    def force(self):
        self._force = True
    @cli.autoswitch(help='update walt embedded software if needed.')
    def update(self):
        self._auto_update = True

@WalTImage.subcommand("publish")
class WalTImagePublish(cli.Application):
    """publish a WalT image on the docker hub"""
    def main(self, image_name):
        q = ResponseQueue()
        with ClientToServerLink() as server_link:
            auth_conf = get_auth_conf(server_link)
            server_link.publish_image(q, auth_conf, image_name)
            server_link.wait_queue(q)

@WalTImage.subcommand("show")
class WalTImageShow(cli.Application):
    """display your working set of walt images"""
    def main(self):
        with ClientToServerLink() as server:
            print server.show_images()

@WalTImage.subcommand("shell")
class WalTImageShell(cli.Application):
    """modify an image through an interactive shell"""
    def main(self, image_name):
        with ClientToServerLink() as server:
            session_info = server.create_image_shell_session(
                            image_name)
            if session_info == None:
                return  # issue already reported
            session_id, image_fullname, container_name, default_new_name = \
                            session_info
            run_image_shell_prompt(image_fullname, container_name)
            try:
                while True:
                    new_name = raw_input(\
                        'New image name [%s]: ' % default_new_name)
                    if new_name == '':
                        new_name = default_new_name
                        print 'Selected: %s' % new_name
                    res = server.image_shell_session_save(
                                    session_id, new_name, name_confirmed = False)
                    if res == 'NAME_NOT_OK':
                        continue
                    if res == 'NAME_NEEDS_CONFIRM':
                        if confirm():
                            server.image_shell_session_save(
                                    session_id, new_name, name_confirmed = True)
                        else:
                            continue
                    break
            except (KeyboardInterrupt, EOFError):
                print 'Aborted.'
            # leaving the API session scoped by the with construct
            # will cause the server to cleanup session data on server side.

@WalTImage.subcommand("remove")
class WalTImageRemove(cli.Application):
    """remove an image from your working set"""
    def main(self, image_name):
        with ClientToServerLink() as server:
            server.remove_image(image_name)

@WalTImage.subcommand("rename")
class WalTImageRename(cli.Application):
    """rename an image of your working set"""
    def main(self, image_name, new_image_name):
        with ClientToServerLink() as server:
            server.rename_image(image_name, new_image_name)

@WalTImage.subcommand("duplicate")
class WalTImageDuplicate(cli.Application):
    """duplicate an image of your working set"""
    def main(self, image_name, new_image_name):
        with ClientToServerLink() as server:
            server.duplicate_image(image_name, new_image_name)

@WalTImage.subcommand("update")
class WalTImageUpdate(cli.Application):
    """update walt internal software in an image"""
    _force = False # default
    def main(self, image_name):
        with ClientToServerLink(True) as server:
            server.update_image(image_name, self._force)
    @cli.autoswitch(help='do it, restart nodes if needed.')
    def force(self):
        self._force = True

@WalTImage.subcommand("cp")
class WalTImageCp(cli.Application):
    """transfer files (client machine <-> image)"""
    def main(self, src, dst):
        with ClientToServerLink() as server:
            info = server.validate_image_cp(src, dst)
            if info == None:
                return
            info = { k:v for k,v in info }
            session_info = server.create_image_shell_session(
                            info['image_tag'])
            if session_info == None:
                return  # issue already reported
            session_id, image_fullname, container_name, default_new_name = \
                            session_info
            info.update(image_fullname = image_fullname,
                        container_name = container_name)
            try:
                run_transfer_with_image(**info)
                if info['client_operand_index'] == 0:
                    # client was sending -> image has been modified
                    # save the image under the same name
                    server.image_shell_session_save(
                            session_id, default_new_name, True)
            except (KeyboardInterrupt, EOFError):
                print
                print 'Aborted.'

