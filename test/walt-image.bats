source $BATS_TEST_DIRNAME/common.sh

ERR_IMAGE_SEARCH="
The following command should output '1', it did not:
walt image search test-suite | grep "$TEST_IMAGE_URL" | wc -l
"

@test "walt image show" {
    walt image show
}

@test "walt image search" {
    num_matches=$(walt image search test-suite | grep "$TEST_IMAGE_URL" | wc -l)
    [ "$num_matches" -eq 1 ] || {
        echo "$ERR_IMAGE_SEARCH" >&2
        return 1    # test failed
    }
}

@test "walt image clone" {
    walt image clone --force "$TEST_IMAGE_URL" | grep Done
    image_exists pc-x86-64-test-suite
}

@test "walt image rename" {
    walt image rename pc-x86-64-test-suite $(bats_test_image) && \
    image_exists $(bats_test_image)
}

@test "walt image duplicate" {
    walt image duplicate $(bats_test_image) $(bats_test_image)-2 && \
    image_exists $(bats_test_image)-2
}

@test "walt image cp" {
    test_walt_cp image $(bats_test_image)
}

@test "walt image shell" {
    test_walt_shell image $(bats_test_image)
}

@test "walt image publish" {
    walt image clone --force "$TEST_IMAGE_URL"
    walt image publish pc-x86-64-test-suite
    walt image remove pc-x86-64-test-suite
}

@test "walt image remove" {
    for image in $(walt image show | grep $(bats_test_image) | awk '{ print $1 }')
    do
        walt image remove $image
        image_exists $image && return 1
    done
    true    # ok if we get here
}
