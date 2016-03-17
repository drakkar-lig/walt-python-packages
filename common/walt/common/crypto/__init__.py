# cryptography design notes
# -------------------------
# we want to keep the installation of walt-client simple
# and portable (pip install walt-client), which forbids the
# use of a python module relying on external libraries,
# such as pycrypto, cryptography, etc. (they require
# python-dev to be installed).
#
# Our need in terms of security is very lightweight:
# * we use encrypted data very rarely (case of 'walt image publish' only)
# * we encrypt a very small amount of data (a password)
#
# Given these facts, we have implemented a simple process:
# At each 'walt image publish' command:
# 1) server and client generate a random key
# 2) an encryption key is agreed using Diffie Hellman process
# 3) the password is encrypted based on this encryption key
#    using a pure-python implementation of the blowfish algorithm.

