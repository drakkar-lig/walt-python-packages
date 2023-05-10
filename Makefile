
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

ALL_PACKAGES=common virtual vpn server node client client-g5k
# common must be installed 1st (needed by others), then virtual
INSTALLABLE_PACKAGES_ON_SERVER=common virtual vpn client server
INSTALLABLE_PACKAGES_ON_CLIENT=common client
INSTALLABLE_PACKAGES_ON_CLIENT_G5K=common client client-g5k
GNUMAKEFLAGS=--no-print-directory

upper=$(shell echo '$1' | tr '[:lower:]-' '[:upper:]_')
ROOT_DIR:=$(shell dirname $(realpath $(firstword $(MAKEFILE_LIST))))
PYTHON:=$(ROOT_DIR)/dev/python.sh
PIP=$(PYTHON) -m pip
BUILD=$(PYTHON) -m build

# ------

install: server.install

%.install:
	$(MAKE) PACKAGES="$(INSTALLABLE_PACKAGES_ON_$(call upper,$*))" install-packages
	[ "$*" = "server" ] && $(ROOT_DIR)/.venv/bin/walt-server-setup || true

install-packages:
	$(MAKE) $(patsubst %,%.uninstall,$(PACKAGES)) $(patsubst %,%.build,$(PACKAGES))
	$(PIP) install $(patsubst %,./%/dist/*.whl,$(PACKAGES))

uninstall: $(patsubst %,%.uninstall,$(ALL_PACKAGES))

pull: $(patsubst %,%.pull,$(INSTALLABLE_PACKAGES_ON_SERVER))

clean: $(patsubst %,%.clean,$(ALL_PACKAGES))

%.clean:
	cd $*; pwd; rm -rf dist build *.egg-info

%.build:
	$(MAKE) $*.info
	$(PIP) show build >/dev/null 2>&1 || $(PIP) install build
	cd $*; pwd; rm -rf dist && $(BUILD)

%.info:
	$(MAKE) $*/walt/$(subst -,/,$*)/info.py

%/info.py: common/walt/common/version.py dev/metadata.py dev/info-updater.py
	$(MAKE) update-info

update-info:
	@echo updating info.py files
	dev/info-updater.py

clean:
	find . -name \*.pyc -delete

%.uninstall:
	$(PIP) show walt-$* >/dev/null 2>&1 && $(PIP) uninstall -y walt-$* || true

upload:
	./dev/upload.sh $(ALL_PACKAGES)

freeze-deps:
	./dev/requirements-updater.py freeze
	$(MAKE) update-info

unfreeze-deps:
	./dev/requirements-updater.py unfreeze
	$(MAKE) update-info

test:
	@./dev/test.sh

test-debug:
	@./dev/test.sh --debug

.PHONY: test test-debug
