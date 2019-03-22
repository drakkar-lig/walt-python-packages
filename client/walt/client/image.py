#!/usr/bin/env python
import os, sys
from plumbum import cli
from walt.client.link import ClientToServerLink
from walt.client.tools import confirm
from walt.client.interactive import run_image_shell_prompt
from walt.client.transfer import run_transfer_with_image
from walt.client.auth import get_auth_conf
from walt.client.application import WalTCategoryApplication, WalTApplication

class WalTImage(WalTCategoryApplication):
    """management of WalT-nodes operating system images"""
    pass

@WalTImage.subcommand("search")
class WalTImageSearch(WalTApplication):
    """search for remote WalT node OS images"""
    def main(self, keyword=None):
        with ClientToServerLink() as server_link:
            server_link.set_busy_label('Searching')
            tty_mode = os.isatty(sys.stdout.fileno())
            server_link.search_images(keyword, tty_mode)

@WalTImage.subcommand("clone")
class WalTImageClone(WalTApplication):
    """clone a remote image into your working set"""
    _force = False # default
    def main(self, clonable_image_link):
        with ClientToServerLink() as server_link:
            server_link.set_busy_label('Validating / Cloning')
            server_link.clone_image(clonable_image_link, self._force)
    @cli.autoswitch(help='do it, even if it overwrites an existing image.')
    def force(self):
        self._force = True

@WalTImage.subcommand("publish")
class WalTImagePublish(WalTApplication):
    """publish a WalT image on the docker hub"""
    def main(self, image_name):
        with ClientToServerLink() as server_link:
            server_link.set_busy_label('Validating / Publishing')
            auth_conf = get_auth_conf(server_link)
            server_link.publish_image(auth_conf, image_name)

@WalTImage.subcommand("show")
class WalTImageShow(WalTApplication):
    """display your working set of walt images"""
    _refresh = False # default
    def main(self):
        with ClientToServerLink() as server:
            print server.show_images(self._refresh)
    @cli.autoswitch(help='resync image list from Docker daemon.')
    def refresh(self):
        self._refresh = True

@WalTImage.subcommand("shell")
class WalTImageShell(WalTApplication):
    """modify an image through an interactive shell"""
    def main(self, image_name):
        with ClientToServerLink() as server:
            session_info = server.create_image_shell_session(
                            image_name, 'shell session')
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
                        if confirm(komsg = None):
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
class WalTImageRemove(WalTApplication):
    """remove an image from your working set"""
    def main(self, image_name):
        with ClientToServerLink() as server:
            server.remove_image(image_name)

@WalTImage.subcommand("rename")
class WalTImageRename(WalTApplication):
    """rename an image of your working set"""
    def main(self, image_name, new_image_name):
        with ClientToServerLink() as server:
            server.rename_image(image_name, new_image_name)

@WalTImage.subcommand("duplicate")
class WalTImageDuplicate(WalTApplication):
    """duplicate an image of your working set"""
    def main(self, image_name, new_image_name):
        with ClientToServerLink() as server:
            server.duplicate_image(image_name, new_image_name)

@WalTImage.subcommand("cp")
class WalTImageCp(WalTApplication):
    """transfer files (client machine <-> image)"""
    def main(self, src, dst):
        with ClientToServerLink() as server:
            info = server.validate_image_cp(src, dst)
            if info == None:
                return
            session_info = server.create_image_shell_session(
                            info['image_name'], 'file transfer')
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

