from walt.server.exports.const import NODES_PATH


def wf_add_dirs(wf, added_dirs, **env):
    # note: some dir entries might already be present because we kept
    # persist_dirs, persist_dir, networks, disks subdirs in the
    # 'prepare' step.
    for d in added_dirs:
        #print(f"exports: create {d}")
        (NODES_PATH / d).mkdir(exist_ok=True)
    wf.next()


def wf_remove_dirs(wf, removed_dirs, **env):
    for d in removed_dirs:
        shutil.rmtree(NODES_PATH / d)
    wf.next()
