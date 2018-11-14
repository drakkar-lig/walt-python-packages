#!/bin/bash

do_subpackages()
{
    for subpackage in $SUBPACKAGES
    do
        cd $subpackage
        $*
        cd ..
    done
}

