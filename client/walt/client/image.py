#!/usr/bin/env python
from plumbum import cli
from walt.client.link import ClientToServerLink, ResponseQueue
from walt.client.tools import confirm
from walt.client.interactive import run_image_shell_prompt
from walt.client.transfer import run_transfer_with_image

class WalTImage(cli.Application):
    """management of WalT-nodes operating system images"""
    pass

@WalTImage.subcommand("search")
class WalTImageSearch(cli.Application):
    """search for remote WalT node OS images"""
    def main(self, keyword=None):
        with ClientToServerLink(True) as server:
            q = ResponseQueue()
            server.search_images(q, keyword)
            print q.get()

@WalTImage.subcommand("clone")
class WalTImageClone(cli.Application):
    """clone a remote image into your working set"""
    _force = False # default
    def main(self, clonable_image_link):
        q = ResponseQueue()
        with ClientToServerLink(True) as server:
            server.clone_image(q, clonable_image_link, self._force)
            q.wait()
    @cli.autoswitch(help='do it, even if it overwrites an existing image.')
    def force(self):
        self._force = True

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
            session = server.create_image_shell_session(
                            image_name)
            if session == None:
                return  # issue already reported
            with session:
                run_image_shell_prompt(session)
                default_new_name = session.get_default_new_name()
                try:
                    while True:
                        new_name = raw_input(\
                            'New image name [%s]: ' % default_new_name)
                        if new_name == '':
                            new_name = default_new_name
                            print 'Selected: %s' % new_name
                        res = session.validate_new_name(new_name)
                        if res == session.NAME_NEEDS_CONFIRM:
                            if confirm():
                                res = session.NAME_OK
                            else:
                                res = session.NAME_NOT_OK
                        if res == session.NAME_OK:
                            break
                        if res == session.NAME_NOT_OK:
                            continue
                    # we left the loop, this means we have a valid name
                    session.select_new_name(new_name)
                except (KeyboardInterrupt, EOFError):
                    print 'Aborted.'

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

@WalTImage.subcommand("cp")
class WalTImageCp(cli.Application):
    """transfer files (client machine <-> image)"""
    def main(self, src, dst):
        with ClientToServerLink() as server:
            info = server.validate_image_cp(src, dst)
            if info == None:
                return
            info = { k:v for k,v in info }
            session = server.create_image_shell_session(
                            info['image_tag'])
            if session == None:
                return  # issue already reported
            with session:
                info.update(session = session)
                try:
                    run_transfer_with_image(**info)
                    if info['client_operand_index'] == 0:
                        # client was sending -> image has been modified
                        # save the image under the same name
                        session.select_new_name(session.get_default_new_name())
                except (KeyboardInterrupt, EOFError):
                    print
                    print 'Aborted.'

