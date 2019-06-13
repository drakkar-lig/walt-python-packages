#!/bin/bash

THIS_DIR="$(cd $(dirname $0); pwd)"
BATS_URL="https://github.com/bats-core/bats-core.git"
BATS_DIRNAME="$THIS_DIR/bats-core"
BATS="$BATS_DIRNAME/bin/bats"

if [ ! -d "$BATS_DIRNAME" ]
then
    git clone $BATS_URL "$BATS_DIRNAME"
fi

$BATS test
