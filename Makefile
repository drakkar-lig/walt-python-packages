
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

ALL_PACKAGES=common virtual vpn server node client client-g5k
# common must be installed 1st (needed by others), then virtual
INSTALLABLE_PACKAGES_ON_SERVER=common virtual vpn server client
GNUMAKEFLAGS=--no-print-directory

# sudo should only be used when not root and not in a virtual env
# (sys.base_prefix == sys.prefix test returns False in a virtual env).
SUDO=$(shell python3 -c 'import os, sys; print("sudo -H" if sys.base_prefix == sys.prefix and os.getuid() != 0 else "")')
PIP=$(shell echo `which pip3`)
PIP_INSTALL=$(PIP) install --ignore-installed greenlet

# ------
install: $(patsubst %,%.wheel,$(INSTALLABLE_PACKAGES_ON_SERVER))
	$(SUDO) $(PIP_INSTALL) $(patsubst %,./%,$(INSTALLABLE_PACKAGES_ON_SERVER))

uninstall: $(patsubst %,%.uninstall,$(INSTALLABLE_PACKAGES_ON_SERVER))

pull: $(patsubst %,%.pull,$(INSTALLABLE_PACKAGES_ON_SERVER))

clean: $(patsubst %,%.clean,$(ALL_PACKAGES))

%.clean: %.info
	@cd $*; pwd; python3 setup.py clean --all

%.wheel: %.info
	@cd $*; pwd; python3 setup.py bdist_wheel

%.info:
	@$(MAKE) $*/walt/$(subst -,/,$*)/info.py

%/info.py: common/walt/common/version.py dev/metadata.py dev/info-updater.py
	@echo updating info.py files
	@dev/info-updater.py

clean:
	find . -name \*.pyc -delete

%.uninstall:
	@$(PIP) show walt-$* >/dev/null && $(SUDO) $(PIP) uninstall -y walt-$* || true

upload:
	@./dev/upload.sh $(ALL_PACKAGES)

%.pull:
	@$(MAKE) $*.uninstall
	@$(SUDO) ./dev/pull.sh $*

test:
	@./dev/test.sh

.PHONY: test
