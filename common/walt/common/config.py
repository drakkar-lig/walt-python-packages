import yaml


def parse_yaml_conf(conf_text):
    return yaml.load(conf_text)


def load_conf(path, optional=False):
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
    try:
        conf = yaml.safe_load(conf_text)
    except Exception:
        if optional:
            print(
                f"WARNING: Configuration file at {path} is not valid yaml or json!"
                " Ignored."
            )
            return None
        else:
            raise Exception(f"Configuration file at {path} is not valid yaml or json!")
    return conf
