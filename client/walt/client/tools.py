def yes_or_no(msg, okmsg="OK.\n", komsg="OK.\n"):
    while True:
        print("%s (y/n):" % msg, end=" ")
        res = input()
        if res == "y":
            if okmsg:
                print(okmsg)
            return True
        elif res == "n":
            if komsg:
                print(komsg)
            return False
        else:
            print("Invalid response.")


def choose(msg="possible values:", **args):
    while True:
        print(msg)
        for k, explain in args.items():
            print("* %s: %s" % (k, explain))
        all_keys = "/".join(args.keys())
        print("selected value (%s):" % all_keys, end=" ")
        res = input()
        if res in args:
            return res
        else:
            print("Invalid response.\n")


def confirm(msg="Are you sure?", komsg="Aborted."):
    return yes_or_no(msg, komsg=komsg)
