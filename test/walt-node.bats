source $BATS_TEST_DIRNAME/common.sh
source $BATS_TEST_DIRNAME/walt-node.sh

@test "walt node show" {
    walt node show
}

@test "walt node create" {
    walt node create $(bats_test_node)
    node_exists $(bats_test_node)
}

@test "walt node rename" {
    walt node rename $(bats_test_node) $(bats_test_node)-2 && \
    node_exists $(bats_test_node)-2 && \
    walt node rename $(bats_test_node)-2 $(bats_test_node)
}

@test "walt node boot" {
    walt image clone --force "$TEST_IMAGE_URL"
    walt image rename pc-x86-64-test-suite $(bats_test_image)
    walt node boot $(bats_test_node) $(bats_test_image)
}

@test "walt node wait" {
    # walt command should not timeout, and return code 0 (OK)
    test_timeout 60 walt node wait $(bats_test_node)
}

@test "walt node blink" {
    test_walt_node_blnk $(bats_test_node)
}

@test "walt node ping" {
    # here, we just check that the command times out (return code 124).
    test_timeout 3 walt node ping $(bats_test_node) || [ "$?" = "124" ]
}

@test "walt node run" {
    walt_node_rn $(bats_test_node) hostname | grep "$(bats_test_node)"
}

@test "walt node expose" {
    test_walt_node_xpse $(bats_test_node)
}

@test "walt node cp" {
    test_walt_cp node $(bats_test_node)
}

@test "walt node shell" {
    test_walt_shell node $(bats_test_node)
}

@test "walt node reboot" {
    walt node reboot $(bats_test_node) && \
    walt node reboot --hard $(bats_test_node)
}

@test "walt node config" {
    # check that when setting netsetup=NAT and rebooting
    # the node gets its default route.
    walt node config $(bats_test_node) netsetup NAT && \
    walt node reboot $(bats_test_node) && \
    walt node wait $(bats_test_node) && \
    walt_node_rn $(bats_test_node) ip route | grep default
}

@test "walt node remove" {
    walt node remove $(bats_test_node) && walt image remove $(bats_test_image)
}
