from walt.server.exports.const import NODES_PATH


def wf_add_symlinks(wf, added_symlinks, **env):
    for sl_target, sl_path in added_symlinks:
        #print(f"exports: create {sl_path}")
        symlink_path = NODES_PATH / sl_path
        mac_dir_path = symlink_path.parent
        target_path = mac_dir_path / sl_target
        # automatically move <mac>/persist_dir (older walt version)
        # to <mac>/persist_dirs/<owner>, or just create
        # <mac>/persist_dirs/<owner> if missing.
        if not target_path.exists():
            if target_path.parent.name == "persist_dirs":
                persist_dir_path = mac_dir_path / "persist_dir"
                if persist_dir_path.exists():
                    target_path.parent.mkdir(exist_ok=True)
                    persist_dir_path.rename(target_path)
                else:
                    target_path.mkdir(parents=True)
        symlink_path.symlink_to(sl_target)
    wf.next()


def wf_remove_symlinks(wf, removed_symlinks, **env):
    for sl_path in removed_symlinks:
        (NODES_PATH / sl_path).unlink()
    wf.next()
