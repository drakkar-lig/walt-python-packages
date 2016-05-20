.PHONY: all node client server common

# common must be 1st (needed by others)
all: common.install server.install node.install client.install

%.install: %/info.py
	$(MAKE) $*.uninstall
	cd $*; pwd; sudo pip install . >/dev/null 2>&1 || sudo pip install .

%/info.py: dev/metadata.py dev/version/update-info.py
	dev/version/update-info.py

clean:
	find . -name \*.pyc -delete

%.uninstall:
	pip show walt-$* >/dev/null && sudo pip uninstall -y walt-$* || true
	echo uninstall done

upload:
	./dev/upload.sh
