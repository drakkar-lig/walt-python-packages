import base64
import pickle


def load_conf(path, optional=False, fast_load_mode=False):
    """Load a configuration file"""
    try:
        conf_text = path.read_text()
    except Exception:
        if path.exists():
            if optional:
                print(f"WARNING: Failed to read configuration at {path}")
                return None
            else:
                raise Exception(f"Failed to read configuration at {path}")
        else:
            if optional:
                return None  # nothing to do, file is optional
            else:
                raise Exception(f"Missing configuration file at {path}")
    old_fast_load, hash_val = None, None
    if fast_load_mode:
        # importing yaml is quite long.
        # we try to avoid it by maintaining a fast-load tag in a commented line.
        # this tag encodes a hash of the file content (comments and empty lines
        # removed) and then the conf dictionary encoded using pickle and base64.
        clean_lines = []
        for line in conf_text.splitlines():
            if line.startswith('# fast-load: '):
                old_fast_load = line[13:]
                continue
            line = line.split('#', maxsplit=1)[0].rstrip()
            if line != "":
                clean_lines.append(line)
        clean_text = '\n'.join(clean_lines)
        from hashlib import blake2s
        h = blake2s(digest_size=12)
        h.update(clean_text.encode())
        hash_val = h.hexdigest()
        if old_fast_load is not None:
            try:
                old_hash_val, old_conf_code = old_fast_load[:24], old_fast_load[24:]
                if hash_val == old_hash_val:
                    # ok the existing fast-load tag is still relevant
                    return pickle.loads(
                        base64.b64decode(old_conf_code.encode('ascii')))
            except Exception:
                pass  # continue with regular yaml loading below
    # fast-load failed, use yaml module
    try:
        import yaml
        conf = yaml.safe_load(conf_text)
        if fast_load_mode:
            # add up-to-date fast-load tag for next time
            conf_code = base64.b64encode(
                pickle.dumps(conf)).decode('ascii')
            fast_load = f"# fast-load: {hash_val}{conf_code}"
            if old_fast_load is not None:
                import re
                conf_text = re.sub(r'# fast-load: [^\n]*', fast_load, conf_text)
            else:
                conf_text = (conf_text.rstrip() +
                             f"\n\n\n# -- walt auto-generated data --\n{fast_load}\n\n")
            path.write_text(conf_text)
        return conf
    except Exception:
        if optional:
            print(
                f"WARNING: Configuration file at {path} is not valid yaml or json!"
                " Ignored."
            )
            return None
        else:
            raise Exception(f"Configuration file at {path} is not valid yaml or json!")
