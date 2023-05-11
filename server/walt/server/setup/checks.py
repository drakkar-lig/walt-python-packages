import sys

# check that we have the python apt module
# (also available via pip, but does not install well on debian,
# so require the distribution package)
try:
    import apt
except:
    print('"apt" module not found. Run the following:')
    print('$ apt update && apt install -y python3-apt')
    sys.exit(1)
