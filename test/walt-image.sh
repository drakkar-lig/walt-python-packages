source $TESTS_DIR/includes/common.sh

define_test "walt image show" as {
    walt image show
}

define_test "walt image search" as {
    walt image search test-suite | grep "$TEST_IMAGE_URL"
}

define_test "walt image clone" as {
    walt image clone --force "$TEST_IMAGE_URL" | grep Done
    image_exists pc-x86-64-test-suite
}

define_test "walt image rename" as {
    walt image rename pc-x86-64-test-suite $(test_suite_image)
    image_exists $(test_suite_image)
}

define_test "walt image duplicate" as {
    walt image duplicate $(test_suite_image) $(test_suite_image)-2 && \
    image_exists $(test_suite_image)-2
}

define_test "walt image cp" as {
    test_walt_cp image $(test_suite_image)
}

define_test "walt image shell" as {
    test_walt_shell image $(test_suite_image)
}

define_test "walt image publish" as {
    walt image clone --force "$TEST_IMAGE_URL"
    walt image publish pc-x86-64-test-suite
    walt image remove pc-x86-64-test-suite
}

define_test "walt image remove" as {
    for image in $(walt image show | grep $(test_suite_image) | awk '{ print $1 }')
    do
        walt image remove $image
        image_exists $image && return 1
    done
    true    # ok if we get here
}
