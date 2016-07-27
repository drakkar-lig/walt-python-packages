
# For debugging, you may interact with testpypi instead of pypi
# by defining the environment variable DEBUG_WITH_TESTPYPI=1.

# ** installing the code on the local machine:
# $ make 					# or make install
# $ make client.install		# install the client only (and common, its dependency)

# ** uploading the code to PyPI (DEBUG_WITH_TESTPYPI *must not* be set):
# $ make upload
# Note: targeting a specific component is not allowed in this case,
#       because the upload number is used for the version of each component,
#       so we must upload them all at once.

# ** uploading the code to testpypi (DEBUG_WITH_TESTPYPI *must* be set to 1):
# $ make upload
# $ make client.upload		# upload the client only (and common, its dependency)

# ** pulling packages from PyPI or testpypi (depending on whether DEBUG_WITH_TESTPYPI is set)
# ** and installing them:
# $ make pull
# $ make client.pull		# pull the client only (and common, its dependency)


ALL_PACKAGES=common server node client clientselector nodeselector
# common must be installed 1st (needed by others)
INSTALLABLE_PACKAGES_ON_SERVER=common server client
GNUMAKEFLAGS=--no-print-directory

# ------
all: $(patsubst %,%.install,$(INSTALLABLE_PACKAGES_ON_SERVER))

pull: $(patsubst %,%.pull,$(INSTALLABLE_PACKAGES_ON_SERVER))

client.%: common.%
server.%: common.%
node.%: common.%

%.install: %.info
	@$(MAKE) $*.uninstall
	@cd $*; pwd; sudo pip install . >/dev/null 2>&1 || sudo pip install .

%.info:
	@$(MAKE) $*/walt/$*/info.py

%/info.py: common/walt/common/versions.py dev/metadata.py dev/version/info-updater.py
	@echo updating info.py files
	@dev/version/info-updater.py

clean:
	find . -name \*.pyc -delete

%.uninstall:
	@pip show walt-$* >/dev/null && sudo pip uninstall -y walt-$* || true

ifeq ($(DEBUG_WITH_TESTPYPI),1)
# test setup: we upload/download the packages on/from testpypi.python.org.
upload: $(patsubst %,%.upload,$(ALL_PACKAGES))

%.upload: %.info
	@cd $*; pwd; python setup.py register -r pypitest >/dev/null; \
	 python setup.py sdist upload -r pypitest >/dev/null

%.pull:
	@$(MAKE) $*.uninstall
	@sudo pip install -i https://testpypi.python.org/simple --upgrade walt-$*

else
# production code, we will perform various checks related to the
# git repository before allowing the upload on PyPI.
upload:
	./dev/upload.sh $(ALL_PACKAGES)

%.pull:
	@$(MAKE) $*.uninstall
	@sudo pip install --upgrade walt-$*
endif

