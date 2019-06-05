def pprint_dict(d, indent=0):
    lines = [ 'dict(' ]
    if len(d) > 0:
        for k, v in list(d.items()):
            if isinstance(v, dict):
                v_repr = pprint_dict(v, indent+1)
            else:
                v_repr = repr(v)
            spaces = ' ' * ((indent+1)*4)
            lines += [ spaces + '%s = %s,' % (k, v_repr) ]
        # remove ',' on last item
        lines[-1] = lines[-1][:-1]
    lines += [ ' ' * (indent*4) + ')' ]
    return '\n'.join(lines)

