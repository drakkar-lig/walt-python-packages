import os

TYPE_CLIENT = 0
TYPE_IMAGE = 1

HELP_INVALID = """\
Usage:
$ walt image cp <local_file_path> <image>:<file_path>
or
$ walt image cp <image>:<file_path> <local_file_path>

Regular files as well as directories are accepted.
"""

def fail_when_path_type_none(requester, path):
    requester.stderr.write("Could not find path %s.\n" % path)

def analyse_file_types(requester, src_path, src_fs, dst_path, dst_fs, **kwargs):
    bad = dict(valid = False)
    dst_dir = None
    src_type = src_fs.get_file_type(src_path)
    dst_type = dst_fs.get_file_type(dst_path)
    if dst_type is None:
        # maybe this is just the target filename, let's verify that the parent
        # directory exists 
        parent_path = os.path.dirname(dst_path)
        if dst_fs.get_file_type(parent_path) == 'd':
            # ok
            dst_type = 'd'
            dst_name = os.path.basename(dst_path)
            dst_dir = parent_path
    for ftype, path in [(src_type, src_path), (dst_type, dst_path)]:
        if ftype is None:
            fail_when_path_type_none(requester, path)
            return bad
    if dst_type == 'f':
        if src_type == 'd':
            requester.stderr.write(
                "Invalid request. " + \
                "Overwriting regular file %s with directory %s is not allowed.\n" % \
                    (dst_path, src_path))
            return bad
        # overwriting a file 
        dst_type = 'd'
        dst_name = os.path.basename(dst_path)
        dst_dir = os.path.dirname(dst_path)
    elif dst_dir is None:
        # copying to a directory, keeping the source name
        dst_name = os.path.basename(src_path)
        dst_dir = dst_path
    kwargs.update(
        valid = True,
        dst_dir = dst_dir,
        dst_name = dst_name
    )
    return kwargs

def validate_cp(images, docker, requester, src, dst):
    invalid = False
    operands = []
    operand_index_per_type = {}
    filesystems = []
    paths = []
    image_tag = None
    for index, operand in enumerate([src, dst]):
        parts = operand.split(':')
        operand_type = len(parts)-1
        if operand_type > 1:
            invalid = True
            break
        operands.append(operand)
        operand_index_per_type[operand_type] = index
        if operand_type == TYPE_CLIENT:
            filesystems.append(requester.filesystem)
            paths.append(operand.rstrip('/'))
        else:
            image_tag, path = parts
            image = images.get_user_image_from_tag(requester, image_tag)
            if not image:
                return
            filesystems.append(image.filesystem)
            paths.append(path.rstrip('/'))
    if len(operand_index_per_type) != 2:
        invalid = True
    if invalid:
        requester.stderr.write(HELP_INVALID)
        return
    src_fs, dst_fs = filesystems
    src_path, dst_path = paths
    info = analyse_file_types(  requester,
                                src_path, src_fs,
                                dst_path, dst_fs)
    if info.pop('valid') == False:
        return
    # all seems fine
    client_operand_index = operand_index_per_type[TYPE_CLIENT]
    info.update(
        src_path = src_path,
        client_operand_index = client_operand_index,
        image_tag = image_tag
    )
    # return an immutable object
    return tuple(info.items())

