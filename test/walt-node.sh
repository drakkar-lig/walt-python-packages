source $TESTS_DIR/includes/common.sh

define_test "walt node show" as {
    walt node show
}

define_test "walt node create" as {
    walt node create $(test_suite_node)
    node_exists $(test_suite_node)
}

define_test "walt node rename" as {
    walt node rename $(test_suite_node) $(test_suite_node)-2
    node_exists $(test_suite_node)-2
    walt node rename $(test_suite_node)-2 $(test_suite_node)
}

define_test "walt node boot" as {
    walt image clone --force "$TEST_IMAGE_URL"
    walt image rename pc-x86-64-test-suite $(test_suite_image)
    walt node boot $(test_suite_node) $(test_suite_image)
}

define_test "walt node wait" as {
    # walt command should not timeout, and return code 0 (OK)
    timeout -s INT 60 walt node wait $(test_suite_node)
}

define_test "walt node blink" as {
    node="$(test_suite_node)"
    status_file="$(mktemp)"

    # run walt node blink
    {
        timeout -s INT 10 walt node blink "$node" 5
    } &

    # in our test image, /bin/blink updates a file /tmp/blink-status.
    # between 0 and 5 seconds it should be "on", then "off"
    sleep 1
    walt node cp $node:/tmp/blink-status $status_file
    cat $status_file >&2 && cat $status_file | grep "on"
    sleep 5
    walt node cp $node:/tmp/blink-status $status_file
    cat $status_file >&2 && cat $status_file | grep "off"

    rm $status_file
}

define_test "walt node ping" as {
    # here, we just check that the command times out (return code 124).
    timeout -s INT 3 walt node ping $(test_suite_node) || [ "$?" = "124" ]
}

define_test "walt node run" as {
    walt node run $(test_suite_node) hostname | grep "$(test_suite_node)"
}

define_test "walt node expose" as {
    node="$(test_suite_node)"

    # run a echo server on the node for 5 seconds
    {
        timeout -s INT 5 walt node run "$node" -- busybox nc -l -p 80 -e /bin/cat
    } &

    # use walt node expose for the same period, to expose the port on local machine
    {
        timeout -s INT 5 walt node expose "$node" 80 46871
    } &

    # check that text is echoed locally
    sleep 2
    echo OK | nc 127.0.0.1 46871 | grep OK
}

define_test "walt node cp" as {
    test_walt_cp node $(test_suite_node)
}

define_test "walt node shell" as {
    test_walt_shell node $(test_suite_node)
}

define_test "walt node reboot" as {
    walt node reboot $(test_suite_node)
    walt node reboot --hard $(test_suite_node)
}

define_test "walt node config" as {
    # check that when setting netsetup=NAT and rebooting
    # the node gets its default route.
    walt node config $(test_suite_node) netsetup NAT
    walt node reboot $(test_suite_node)
    walt node wait $(test_suite_node)
    walt node run $(test_suite_node) ip route | grep default
}

define_test "walt node remove" as {
    walt node remove $(test_suite_node)
    walt image remove $(test_suite_image)
}
