
# Repository: walt-python-packages

This section explains various topics helpful to understand how is organised
the main WalT platform code repository at
https://github.com/drakkar-lig/walt-python-packages.


## Sub-directories, relation with pip packages

This single github repository allows to build and upload various pip-installable
python packages on pypi.org:

| Package on pypi | Sub-dir    | Most of python code at:    | Imported as:    |
|-----------------|------------|----------------------------|-----------------|
| walt-client     | client     | client/walt/client         | walt.client     |
| walt-client-g5k | client-g5k | client-g5k/walt/client/g5k | walt.client.g5k |
| walt-common     | common     | common/walt/common         | walt.common     |
| walt-doc        | doc        | doc/walt/doc               | walt.doc        |
| walt-node       | node       | node/walt/node             | walt.node       |
| walt-server     | server     | server/walt/server         | walt.server     |
| walt-virtual    | virtual    | virtual/walt/virtual       | walt.virtual    |
| walt-vpn        | vpn        | vpn/walt/vpn               | walt.vpn        |

You can find walt-server package at https://pypi.org/project/walt-server for instance
(this is the same for others).

Developing all these python packages in the same git repository makes development
of features involving several components easier.
The actual location of python code results from this structure. For instance,
subdirectory `common` is the root of `walt-common` package code. So one can find
the file `common/setup.py` there (only after running `make install` at least once,
since this file is generated), but most other files of the package are at
`common/walt/common/<some-file>.py` in order to allow statements such as
`from walt.common import <some-file>`.

As can be seen in the last column, all python packages share the same parent source
package called `walt`. This is called a "namespace package".
There are several ways to handle namespace packages, as can be seen [in the doc](https://packaging.python.org/en/latest/guides/packaging-namespace-packages/).
Currently the code is using the `pkgutil` method described there.

Note that `walt.client` is also a namespace package, which allows to manage optional
client plugins. `walt-client-g5k` is the only such plugin at the moment (extension
for running walt on Grid'5000).

The remaining sub-directories are:
* dev: a collection of development scripts or metadata involved in Makefile targets
* test: the collection of tests involved in `make test`


## About the code of each package

The purpose of each package should be obvious given its name. The only exception
is `walt-node`. It is an optional package which may be installed on some WalT images
(for instance the default images have it). It currently allows more powerful logging
features, handling faster kexec-based reboots, etc.

We have dedicated documentation pages for the following components:
* `walt-client`: see [`walt help show dev-client`](dev-client.md)
* `walt-server`: see [`walt help show dev-server`](dev-server.md)

If you need documentation about another component, please email us:
`walt-contact at univ-grenoble-alpes.fr`


## Makefile targets

Most often used:

* `make install` or `make -j install`: build and install everything needed on the
  server, i.e., all pip packages except `walt-client-g5k` and `walt-node`. Option `-j`
  runs a parallel build.
* `make quick-venv-update`: very lightweight version of `make install`, which just
  copies to the virtual environment directory the files git reports as modified in
  the working directory.
* `make doc.install`: compile markdown docs into html, update virtual env (hitting the
  refresh button of your browser pointing at `http://<walt-server>/doc` should then
  be enough to reflect modifications).
* `make test`: run the test suite.

Little used:

* `make <subdir>.build`: build a specific pip package. For instance: `make node.build`.
  Built files are generated at `<subdir>/dist/`.
* `make upload`: upload packages to the PyPI when a new walt version is published.
* `make freeze-deps` & `make unfreeze-deps`: see management of dependencies below.


## Versions and dependencies

### Specifying versions and dependencies

Files `<subdir>/setup.py` and `server/requirements.txt` are generated, so do not try
to modify them directly. Modify `dev/metadata.py` instead.

Dependencies between walt packages are simple: for instance, `walt-client` version
`8.0` has a dependency on `walt-common==8.0` and `walt-doc==8.0`.
We do not support dependencies between walt packages of different versions.

The main reasons for generating `setup.py` files and `server/requirements.txt`
dynamically are:
* To have the current walt version number written at only one place (it is at
  `common/walt/common/version.py`).
* To avoid duplicating information in `server/setup.py` and `server/requirements.txt`.
* To factorize some code present in all `setup.py` files.

Package `walt-client`, and its dependencies `walt-doc` and `walt-common` should be
easily installable, because some people may install it on other machines (instead of
just using the client installed on the walt server). This case became more common
since we now provide python scripting features in the walt client package. Easily
installable means we must avoid depending on complex packages, such as packages
involving compiled extensions. Packages `walt-client`, `walt-doc` and `walt-common`
must rely on pure-python dependencies only. And we should try to limit the number
of dependencies of those packages.

The other packages installed on the server do not have those restrictions, because
server installation docs describe quite fine requirements about the OS and machine
on which `walt-server` should be installed, so even complex dependencies should
install just fine. In fact, package `walt-vpn` relies on a compiled extension itself.

Package dependencies are described in `dev/metadata.py`, in a loose way:
`<dependency> >= <version>` (unless a specific issue requires more elaborate criteria).

All `setup.py` files (auto-generated) contain the same dependency specifications as
in `dev/metadata.py`, except `server/setup.py`.

Files `server/setup.py` and `server/requirements.txt` are special: they specify a fixed
version number for all dependencies and sub-dependencies (dependencies of dependencies).
Since the list is long, we have had quite a few issues in the past, for instance a newer
version of a sub-dependency could break the direct server dependency which was using it.
Fixing all version numbers solved this kind of problem. We can afford this because the
walt server is not designed to be directly accessible from the internet, so fixing a
security issue which happen to be discovered on one of its dependencies is never an
urgent matter. We favor stability over frequent security updates.

Using `make unfreeze-deps` allows to release the fixed version requirements in
`server/setup.py` and `server/requirements.txt`. This can be used in case of a
development requiring a significant python environment upgrade (OS upgrade, adding a
dependency conflicting with others, etc.). After running `make unfreeze-deps`, run
`make install`. Check if everything works. You can also run `pip check` to verify that
no package conflict remains. If all is fine, run `make freeze-deps` to restore a setup
with fixed version requirements, but with the versions of the libraries you just
tested, those of the virtual environment you modified.


### Functional dependencies

`walt-client` will not work with a server running a different version.
It will however detect the version mismatch and propose to upgrade or downgrade.

As a reminder, the package `walt-node` is optional and may be installed on some
WalT images (e.g., default ones, but not minimalistic ones). Since we want to be
able to use old walt images on a newer walt platform and vice versa, the code in
`walt-node` should not depend on specific walt server features (and vice versa),
or there should be a way to detect and adapt to the situation.


## Compatibility with python 3.9

We must avoid using bleeding-edge python features in `walt-client` code,
and it dependencies (`walt-common`, `walt-doc`) because we want the client to
be installable on machines with a python version a little older than the one
on the server.

The same kind of restriction applies to the code involved in `walt-server-setup`:
in some cases, this tool has to upgrade the OS, which implies it is first called
with the python interpreter of the old OS.
The code of `walt-server-setup` is at `server/walt/server/setup/` and relies
on some code of `walt-common`, `walt-doc`, and `walt-vpn` (setup part too).

The remaining server code can theoretically use modern python features,
but for coherency we avoid using python features not supported by python 3.9.


## Package entry points and special embedded content

In addition to the python code, each package may define:
* python console scripts to be installed
* shell scripts to be installed
* arbitrary files to embed with the source code
* compiled extensions

Note: see above for restrictions about `walt-client`, `walt-common`, and `walt-doc`
which must be easily installable and usable on any machine; those packages should
not define shell scripts or compiled extensions.

Defining a python console script requires adding an entry in the `"console_scripts"`
table of the relevant package in `dev/metadata.py`.
An obvious example is the `walt` command defined in the `walt-client` package.

Defining a shell script to be installed with the package requires adding an
entry in the `"scripts"` table of the relevant package in `dev/metadata.py`.
Check-out existing definitions for reference.

Embedding arbitrary files requires two steps:
* To ensure the relevant package defines a flag `include_package_data=True`
  in `dev/metadata.py`
* To have the files declared in `<subdir>/MANIFEST.in`

Those arbitrary files are then installed next to the python source code.
The source code can load them when needed. Various examples in current source code
use module `pkg_resources` for that purpose.
See `server/walt/server/processes/main/network/tftp.py` for instance.

For compiled extensions, refer to the definition of package `walt-vpn` in
`dev/metadata.py`.


## Testing and writing new tests

A collection of tests is implemented in the `test` directory.
Some of them are shell scripts, others are python scripts.

Tests are very high-level (e.g. test walt client tool sub-commands, API functions),
so they must be run on a working WALT development platform.

Run `make test` to test all.

If you want to run the reduced set of tests contained in a file `test/<name>.[sh|py]`,
run `dev/test.sh <name>`.
For instance `dev/test.sh walt-node` will only run the tests defined in
`test/walt-node.sh`; Similarly, `dev/test.sh api-logs` will only run the tests defined
in `test/api-logs.py`.

Notes and requirements to follow when adding new tests:
* The format of sh and py files should be obvious when looking at the existing tests.
* Each file `test/<name>.[sh|py]` must be "self-contained": if all tests succeed,
  it should leave the platform in a clean state. Side effects are allowed for a given
  test as long as next tests of the file clean them up. For instance, one of the first
  tests in `test/walt-image.py` is about `walt image clone`, so this test downloads an
  image from the docker hub; but the last test is about `walt image remove`, so this
  image is finally removed before the file ends. The only case which may require the
  developer to manually clean things up should be the case of failing tests.
* `includes/common.sh` and `includes/common.py` define several useful functions, for
  instance `test_suite_node` and `test_suite_image`; checkout current tests for usage.


## Writting new documentation files

Documentation is written in `doc/walt/doc/md/<topic>.md` markdown files.
The left column on `http://<walt-server>/doc` is generated from file
`doc/walt/doc/sphinx/index_rst_tables`. It is mandatory to have all markdown files
referenced in this `index_rst_tables` file. If not, `make doc.install` (and, by
extension, `make install`) fails.

The file must start with a short level-1 header (i.e. prefixed with 1 hashtag),
starting with an uppercase char.
This level-1 header is quite important since it is visible in `walt help list` and
displayed when autocompleting help topics in `walt help show <topic>`.

In the remaining of the file you can use level-2 or level-3 headers to organize the
content. Avoid level-4 or more headers (write other help topics instead).

You can refer to another topic, say `log-echo`, by writting something like this:
```
See [`walt help show log-echo`](log-echo.md) for more info.
```
Those links are automatically detected and adapted for proper rendering and linking
in html docs (e.g., on `http://<walt-server>/doc`), or when viewing source markdown
directly on github.com, and when using the command line viewer
(`walt help show <topic>`).

You can test your modifications by typing `make doc.install` and then viewing
`http://<walt-server>/doc` on your browser, or typing `walt help show <topic>`.


## Checklist for a new feature

When commiting a new feature, check that your modifications include, when relevant:
* new tests in `test/` subdir (at least for new walt client subcommands or API features)
* new documentation in `doc/walt/doc/md/<topic>.md` files and related entries in
  `doc/walt/doc/sphinx/index_rst_tables` -- test it with `walt help show <topic>`
* in case of a new walt client subcommand involving specific arguments, appropriate
  auto-completion processing for these arguments in
  `server/walt/server/processes/main/autocomplete.py`
