
ERR_IMAGE_SEARCH="
The following command should output '1', it did not:
walt image search test-suite | grep 'hub:eduble/pc-x86-64-test-suite' | wc -l
"

bats_test_image() {
    if [ ! -e /tmp/bats_test_image ]
    then
        echo pc-x86-64-test-suite-$$ > /tmp/bats_test_image
    fi
    cat /tmp/bats_test_image
}

image_exists() {
    walt image show | grep "$1 "
}

@test "walt image show" {
    walt image show
}

@test "walt image search" {
    num_matches=$(walt image search test-suite | grep 'hub:eduble/pc-x86-64-test-suite' | wc -l)
    [ "$num_matches" -eq 1 ] || {
        echo "$ERR_IMAGE_SEARCH" >&2
        return 1    # test failed
    }
}

@test "walt image clone" {
    walt image clone --force hub:eduble/pc-x86-64-test-suite | grep Done
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
    tempdir=$(mktemp -d)
    checkfile=$(mktemp -u)
    echo $$ > $tempdir/testfile
    walt image cp $tempdir $(bats_test_image):/tmp/  &&
    walt image cp $(bats_test_image):/tmp/$(basename $tempdir)/testfile $checkfile
    diff $tempdir/testfile $checkfile && rm -rf $tempdir $checkfile
}

@test "walt image shell" {
    which expect || skip 'This test requires the "expect" command.'

    expect << EOF
set timeout 5
spawn walt image shell $(bats_test_image)
expect "# \$"
send "echo ok > /tmp/test\r"
expect "# \$"
send "exit\r"
expect ": \$"
send "\r"
send "y\r"
expect "updated.\$"
EOF

    checkfile=$(mktemp -u)
    walt image cp $(bats_test_image):/tmp/test $checkfile
    out=$(cat $checkfile)
    rm -f $checkfile
    [ "$out" = "ok" ]
}

@test "walt image publish" {
    walt image clone --force hub:eduble/pc-x86-64-test-suite
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
