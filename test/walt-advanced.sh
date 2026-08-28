source $TESTS_DIR/includes/common.sh

define_test "walt advanced sql" as {
    result="$(echo "\dt" | walt advanced sql | grep -c logstreams)"
    [ $result -eq 1 ]
}

define_test "walt advanced update-hub-meta" as {
    walt advanced update-hub-meta
}

define_test "walt advanced dump-bash-autocomplete" as {
    autocomp_file=$(mktemp)
    walt advanced dump-bash-autocomplete > $autocomp_file
    bash $autocomp_file   # check we got regular bash code
    rm $autocomp_file
}

define_test "walt advanced dump-zsh-autocomplete" as {
    which zsh >/dev/null || {
        skip_test 'requires the "zsh" command'
    }

    autocomp_file=$(mktemp)
    walt advanced dump-zsh-autocomplete > $autocomp_file
    zsh $autocomp_file   # check we got regular zsh code
    rm $autocomp_file
}

define_test "walt advanced update-default-images" as {
    walt advanced update-default-images
}

define_test "walt advanced set-free-nodes-image" as {
    walt image clone --force "$TEST_IMAGE_URL"
    image_exists pc-x86-64-test-suite
    walt advanced "set-free-nodes-image" \
        pc-x86-64 pc-x86-64-test-suite
    walt advanced "set-free-nodes-image" \
        pc-x86-64 default
    walt image remove "set-free-nodes-image"
}
