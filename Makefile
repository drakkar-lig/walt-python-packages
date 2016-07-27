
# ** installing the code on the local machine:
# $ make 					# or make install
# $ make client.install		# install the client only (and common, its dependency)

# ** uploading the code to pypi (python package index) or pypitest
# $ make upload				# upload all packages
#
# Notes:
# - upload is directed to the appropriate repo depending on which git branch you are in:
#     - master  -> pypi
#     - test    -> pypitest
#     - [other] -> [forbidden]
# - targeting a specific component is not allowed in this case,
#   because the upload number is used for the version of each component,
#   so we must upload them all at once.

# ** pulling packages from pypi (python package index) or pypitest
# ** and installing them:
# $ make pull				# pull common, client and server
# $ make client.pull		# pull the client only (and common, its dependency)
#
# Notes:
# - pulling is performed from the appropriate repo depending on which git branch you are in:
#     - master  -> pypi
#     - test    -> pypitest
#     - [other] -> [forbidden]

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

upload:
	@./dev/upload.sh $(ALL_PACKAGES)

%.pull:
	@$(MAKE) $*.uninstall
	@sudo ./dev/pull.sh $*

