
import re, itertools

# iterate over "names" ensuring they are all different.
# if 2 names match, add suffix "(2)", then "(3)", etc.
def iter_uniq(names, conflict_pattern='%s(%d)'):
    seen = set()
    for name in names:
        if name in seen:
            for i in itertools.count(start=2):
                alt_name = conflict_pattern % (name, i)
                if alt_name not in seen:
                    name = alt_name
                    break
        seen.add(name)
        yield name

def snakecase(name):
    name = re.sub('[^ a-zA-Z0-9]', ' ', name)
    name = re.sub('([a-z])([A-Z])', r'\1 \2', name)   # if it was camel case
    return '_'.join(w.lower() for w in name.split())

def create_names_dict(named_objects, name_format = None):
    it1, it2 = itertools.tee(named_objects)
    names, objects = (t[0] for t in it1), (t[1] for t in it2)
    if name_format is not None:
        names = (name_format(name) for name in names)
    names = iter_uniq(names, conflict_pattern='%s_%d')
    return dict(zip(names, objects))


