#!/usr/bin/env python
import re

from plumbum import cli
from walt.client.application import WalTApplication, WalTCategoryApplication
from walt.client.config import conf
from walt.client.link import ClientToServerLink
from walt.client.tools import confirm
from walt.client.types import (
    IMAGE,
    IMAGE_BUILD_NAME,
    IMAGE_CLONE_URL,
    IMAGE_CP_DST,
    IMAGE_CP_SRC,
)

MSG_WS_IS_EMPTY = """\
Your working set is empty.
Use 'walt image search [<keyword>]' to search for images
you could build upon.
Then use 'walt image clone <clonable_link>' to clone them
into your working set.
"""


class WalTImage(WalTCategoryApplication):
    """management of WalT-nodes operating system images"""

    ORDERING = 1


@WalTImage.subcommand("search")
class WalTImageSearch(WalTApplication):
    """search for remote WalT node OS images"""

    ORDERING = 2

    def main(self, keyword=None):
        with ClientToServerLink() as server_link:
            server_link.set_busy_label("Searching")
            server_link.search_images(keyword)


@WalTImage.subcommand("clone")
class WalTImageClone(WalTApplication):
    """clone a remote image into your working set"""

    ORDERING = 3
    _force = False  # default

    def main(self, clonable_image_link: IMAGE_CLONE_URL, image_name=None):
        with ClientToServerLink() as server_link:
            server_link.set_busy_label("Validating / Cloning")
            res = server_link.clone_image(
                clonable_image_link, force=self._force, image_name=image_name
            )
            if res["status"] == "OK":
                print(
                    f'Image "{res["image_name"]}" was cloned successfully'
                    " (cf. walt image show)."
                )
                return True  # success
            else:
                return False  # issue

    @cli.autoswitch(help="do it, even if it overwrites an existing image.")
    def force(self):
        self._force = True


@WalTImage.subcommand("publish")
class WalTImagePublish(WalTApplication):
    """publish a WalT image on the hub (or other registry)"""

    ORDERING = 10
    registry = cli.SwitchAttr(
        ["--registry"],
        str,
        argname="REGISTRY",
        default="auto",
        help="""select which image registry to publish to""",
    )

    def main(self, image_name: IMAGE):
        with ClientToServerLink() as server_link:
            from walt.common.formatting import columnate
            registries = server_link.get_registries()
            if len(registries) == 0:
                print("Sorry, no image registry is configured on this platform.")
                return False
            if self.registry == "auto":
                if len(registries) > 1:
                    print("Several image registries are configured on this platform:")
                    print()
                    print(columnate(registries, ("Registry", "Description")))
                    print()
                    print(
                        "Please specify the target registry by using option"
                        " '--registry'."
                    )
                    return False
                # there is a single registry => 'auto' is OK.
                self.registry = registries[0][0]
            else:
                if self.registry not in tuple(reg_info[0] for reg_info in registries):
                    print(f"Invalid registry '{self.registry}'.")
                    print("The following registries are available:")
                    print()
                    print(columnate(registries, ("Registry", "Description")))
                    return False
            server_link.set_busy_label("Validating / Publishing")
            res = server_link.publish_image(self.registry, image_name)
            if res[0] is False:
                return False
            print(f"OK, image was published at:\n{res[1]}")


@WalTImage.subcommand("show")
class WalTImageShow(WalTApplication):
    """display your working set of walt images"""

    ORDERING = 1
    _refresh = False  # default
    _names_only = False  # default

    def main(self):
        if self._names_only:
            fields = ("name",)
        else:
            fields = ("name", "in_use", "created", "compatibility:compact")
        with ClientToServerLink() as server:
            tabular_data = server.get_images_tabular_data(
                conf.walt.username, self._refresh, fields
            )
        if self._names_only:
            print("\n".join(row[0] for row in tabular_data))
        else:
            if len(tabular_data) == 0:
                print(MSG_WS_IS_EMPTY)
            else:
                header = list(
                    re.sub(r"([^:]*):.*", r"\1", f).capitalize().replace("_", "-")
                    for f in fields
                )
                from walt.common.formatting import columnate
                print(columnate(tabular_data, header))

    @cli.autoswitch(help="resync image list from podman storage")
    def refresh(self):
        self._refresh = True

    @cli.autoswitch(help="list image names only")
    def names_only(self):
        self._names_only = True


@WalTImage.subcommand("shell")
class WalTImageShell(WalTApplication):
    """modify an image through an interactive shell"""

    ORDERING = 4

    def main(self, image_name: IMAGE):
        with ClientToServerLink() as server:
            session_info = server.create_image_shell_session(
                image_name, "shell session"
            )
            if session_info is None:
                return  # issue already reported
            session_id, image_fullname, container_name, default_new_name = session_info
            from walt.client.interactive import run_image_shell_prompt
            run_image_shell_prompt(image_fullname, container_name)
            try:
                while True:
                    print("------")
                    print("You can save changes as a new image, or overwrite this one.")
                    print("Just press <enter> to reuse the name "
                          f'"{default_new_name}" and overwite the image.')
                    print("You can also press ctrl-C to abort.")
                    print("------")
                    new_name = input("New image name: ")
                    if new_name == "":
                        new_name = default_new_name
                        print("Selected: %s" % new_name)
                    res = server.image_shell_session_save(
                        conf.walt.username, session_id, new_name, name_confirmed=False
                    )
                    if res == "NAME_NOT_OK":
                        continue
                    if res == "NAME_NEEDS_CONFIRM":
                        if confirm(komsg=None):
                            server.image_shell_session_save(
                                conf.walt.username,
                                session_id,
                                new_name,
                                name_confirmed=True,
                            )
                        else:
                            continue
                    break
            except (KeyboardInterrupt, EOFError):
                print("Aborted.")
            # leaving the API session scoped by the with construct
            # will cause the server to cleanup session data on server side.


@WalTImage.subcommand("remove")
class WalTImageRemove(WalTApplication):
    """remove an image from your working set"""

    ORDERING = 8

    def main(self, image_name: IMAGE):
        with ClientToServerLink() as server:
            return server.remove_image(image_name)


@WalTImage.subcommand("rename")
class WalTImageRename(WalTApplication):
    """rename an image of your working set"""

    ORDERING = 9

    def main(self, image_name: IMAGE, new_image_name):
        with ClientToServerLink() as server:
            return server.rename_image(image_name, new_image_name)


@WalTImage.subcommand("duplicate")
class WalTImageDuplicate(WalTApplication):
    """duplicate an image of your working set"""

    ORDERING = 7

    def main(self, image_name: IMAGE, new_image_name):
        with ClientToServerLink() as server:
            return server.duplicate_image(image_name, new_image_name)


@WalTImage.subcommand("build")
class WalTImageBuild(WalTApplication):
    """build a WalT image using a Dockerfile"""

    ORDERING = 5
    USAGE = """\
    walt image build --from-url <git-repo-url> <image-name>
    walt image build --from-dir <local-directory> <image-name>

    See 'walt help show image-build' for more info.
    """
    src_url = cli.SwitchAttr(
        "--from-url",
        str,
        argname="GIT_URL",
        default=None,
        help="""Git repository URL containing a Dockerfile""",
    )
    src_dir = cli.SwitchAttr(
        "--from-dir",
        str,
        argname="DIRECTORY",
        default=None,
        help="""Local directory containing a Dockerfile""",
    )

    # note: we should not use type IMAGE like most other subcommands
    # because IMAGE only selects existing image names whereas the user
    # can specify a new image name here.
    def main(self, image_name: IMAGE_BUILD_NAME):
        if self.src_url is None and self.src_dir is None:
            print("You must specify 1 of the options --from-url and --from-dir.")
            print("See 'walt help show image-build' for more info.")
            return
        mode = "dir" if self.src_url is None else "url"
        with ClientToServerLink() as server:
            info = dict(mode=mode, image_name=image_name)
            if mode == "dir":
                info["src_dir"] = self.src_dir
            else:
                info["url"] = self.src_url
            info = server.create_image_build_session(**info)
            if info is None:
                return False  # issue already reported
            image_overwrite = info.pop("image_overwrite")
            if image_overwrite:
                if not confirm():
                    return False
            session_id = info.pop("session_id")
            if mode == "dir":
                from walt.client.transfer import run_transfer_for_image_build
                try:
                    if not run_transfer_for_image_build(**info):
                        print("See 'walt help show image-build' for help.")
                        return False
                except (KeyboardInterrupt, EOFError):
                    print()
                    print("Aborted.")
                    return False
            else:
                if not server.run_image_build_from_url(session_id):
                    # failed
                    print("See 'walt help show image-build' for help.")
                    return False
            server.finalize_image_build_session(session_id)


@WalTImage.subcommand("cp")
class WalTImageCp(WalTApplication):
    """transfer files (client machine <-> image)"""

    ORDERING = 6
    USAGE = """\
    walt image cp <local-path> <image>:<path>
    walt image cp <image>:<path> <local-path>
    """

    def main(self, src: IMAGE_CP_SRC, dst: IMAGE_CP_DST):
        with ClientToServerLink() as server:
            info = server.validate_image_cp(src, dst)
            if info is None:
                return
            if info["status"] == "NEEDS_CONFIRM":
                if confirm():
                    info["status"] = "OK"
                else:
                    return  # give up
            if info["status"] == "FAILED":
                return
            session_info = server.create_image_shell_session(
                info["image_name"], "file transfer"
            )
            if session_info is None:
                return  # issue already reported
            session_id, image_fullname, container_name, default_new_name = session_info
            info.update(image_fullname=image_fullname, container_name=container_name)
            from walt.client.transfer import run_transfer_with_image
            try:
                run_transfer_with_image(**info)
                if info["client_operand_index"] == 0:
                    # client was sending -> image has been modified
                    # save the image under the same name
                    server.image_shell_session_save(
                        conf.walt.username, session_id, default_new_name, True
                    )
            except (KeyboardInterrupt, EOFError):
                print()
                print("Aborted.")


@WalTImage.subcommand("squash")
class WalTImageSquash(WalTApplication):
    """squash all layers of an image into one"""

    ORDERING = 11

    def main(self, image_name: IMAGE):
        with ClientToServerLink() as server:
            status = server.squash_image(image_name, False)
            if status == "NEEDS_CONFIRM":
                if confirm():
                    server.squash_image(image_name, True)
