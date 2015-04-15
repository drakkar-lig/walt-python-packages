
# use the following like this:
#
# with AutoCleaner(<cls>) as <var>:
#     ... work_with <var> ...
#
# the <cls> must provide a method cleanup() 
# that will be called automatically when leaving 
# the with construct. 

class AutoCleaner(object):
    def __init__(self, cls):
        self.cls = cls
    def __enter__(self):
        self.instance = self.cls()
        return self.instance
    def __exit__(self, t, value, traceback):
        self.instance.cleanup()
        self.instance = None

