
TEST_IMAGE_URL='hub:eduble/pc-x86-64-test-suite'

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

bats_test_node() {
    if [ ! -e /tmp/bats_test_node ]
    then
        echo testnode-$$ > /tmp/bats_test_node
    fi
    cat /tmp/bats_test_node
}

node_exists() {
    walt node show --all | grep "$1 "
}

test_timeout() {
    seconds="$1"
    shift
    # we have to run this in a subprocess, otherwise it will cause a problem
    # with the display of subsequent test results (probably an issue related to
    # the SIGINT signal which is sent by the timeout command).
    {
        timeout -s INT $seconds "$@"
    } &
    wait -n
}

test_walt_cp() {
    category="$1"
    target="$2"
    tempdir=$(mktemp -d)
    checkfile=$(mktemp -u)
    echo $$ > $tempdir/testfile
    walt $category cp $tempdir $target:/tmp/  &&
    walt $category cp $target:/tmp/$(basename $tempdir)/testfile $checkfile
    diff $tempdir/testfile $checkfile && rm -rf $tempdir $checkfile
}

test_walt_shell() {
    category="$1"
    target="$2"
    which expect || skip 'This test requires the "expect" command.'

    if [ "$category" = "node" ]
    then
        expect << EOF
set timeout 5
spawn walt node shell $target
expect "# \$"
send "echo ok > /tmp/test\r"
expect "# \$"
send "exit\r"
expect "closed.\$"
EOF
    else    # image
        expect << EOF
set timeout 5
spawn walt image shell $target
expect "# \$"
send "echo ok > /tmp/test\r"
expect "# \$"
send "exit\r"
expect ": \$"
send "\r"
send "y\r"
expect "updated.\$"
EOF
    fi
    checkfile=$(mktemp -u)
    walt $category cp $target:/tmp/test $checkfile
    out=$(cat $checkfile)
    rm -f $checkfile
    [ "$out" = "ok" ]
}
