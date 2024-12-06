#!/bin/sh

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
fi

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

# restore the original version
if [ "$BUILD_KEEP_VERSION" != "1" ]
then
    dev/set-version.sh $version
fi
