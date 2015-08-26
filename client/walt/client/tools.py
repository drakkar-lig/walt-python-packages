
def confirm():
    while True:
        print 'Are you sure? (y/n):',
        res = raw_input()
        if res == 'y':
            return True
        if res == 'n':
            return False

