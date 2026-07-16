#!/bin/sh

# stop in case of error
set -e

packages="$*"
if [ "$packages" = "" ]
then
    echo "Usage: $0 <package> [<package>...]"
    exit 1
fi

# unless BUILD_KEEP_VERSION was set by caller (e.g., by dev/upload.sh)
# update the version with indication about the git hash.
if [ "$BUILD_KEEP_VERSION" != "1" ]
then
    version=$(dev/get-version.sh)
    version_with_hash=$(dev/get-version-with-git-hash.sh)

    dev/set-version.sh $version_with_hash
    # restore version before exiting
    trap "cd $PWD; dev/set-version.sh $version" EXIT
fi

# when compiling C extensions enable all warnings
# and consider them as errors (stop the build).
export CFLAGS="$CFLAGS -Werror -Wall"

# build the packages
for package in $packages
do
    if [ "$package" = "doc" ]
    then
        dev/compile-doc.sh $PWD
    fi

    make $package/setup.py

    cd $package
    pwd
    rm -rf dist && ../dev/python.sh -m build

    cd ..
done
