from walt.server.exttools import podman
import uuid

def get_commit_temp_image():
    return 'localhost/walt/commit-temp:' + str(uuid.uuid4()).split('-')[0]

def commit_image(repo, cid_or_cname, dest_fullname, tool=podman, opts=()):
    # we commit with 'docker' format to make these images compatible with
    # older walt server versions
    opts += ('-f', 'docker')
    if repo.image_exists(dest_fullname):
        # take care not making previous version of image a dangling image
        image_tempname = get_commit_temp_image()
        args = opts + (cid_or_cname, image_tempname)
        image_id = tool.commit(*args).strip()
        tool.rm(cid_or_cname)
        podman.rmi('-f', repo.add_repo(dest_fullname))
        podman.tag(image_tempname, repo.add_repo(dest_fullname))
        podman.rmi(image_tempname)
    else:
        args = opts + (cid_or_cname, repo.add_repo(dest_fullname))
        image_id = tool.commit(*args).strip()
        tool.rm(cid_or_cname)
    repo.associate_name_to_id(dest_fullname, image_id)

def commit(server, cid_or_cname, image_fullname, **kwargs):
    walt_local_repo = server.repository
    commit_image(walt_local_repo, cid_or_cname, image_fullname, **kwargs)
