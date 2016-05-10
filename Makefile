.PHONY: all node client server common

# common must be 1st (needed by others)
all: common server node client

common server client node:
	cd $(@); pwd; sudo pip install . >/dev/null

clean:
	find . -name \*.pyc -delete

install-clean:
	rm -rf /usr/local/lib/python*/*packages/walt*

