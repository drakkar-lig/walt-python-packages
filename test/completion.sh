source $TESTS_DIR/includes/common.sh

define_test "testing auto completions" as {
    node=$(test_suite_node)
    image=$(test_suite_image)
    tmp_dir=$(mktemp -d)
    touch $tmp_dir/script.sh

    # prepare node and image
    walt node create $node
    walt image clone --force "$TEST_IMAGE_URL"
    walt image rename pc-x86-64-test-suite $image
    walt node wait $node

    # prepare completion tokens to test
    node_prefix=${node:0:-1}
    node_suffix=${node: -1}
    image_prefix=${image:0:-1}
    image_suffix=${image: -1}

    # run various autocompletion tests
    $TESTS_DIR/includes/autocomplete.exp << EOF
test_tab_complete "walt help show ad" "min "
test_tab_complete "walt node reboot ${node},my-n" "odes"
test_tab_complete "walt node shell $node_prefix" "$node_suffix "
test_tab_complete "walt image shell $image_prefix" "$image_suffix "
test_tab_complete "walt node cp $node:/bi" "n/"
test_tab_complete "walt node cp $tmp_dir/scri" "pt.sh "
test_tab_complete "walt node cp $tmp_dir/script.sh $node:/tm" "p/"
test_tab_complete "walt image cp $image:/bin/gunz" "ip "
test_tab_complete "walt image cp $image:/bin/gunzip $tmp_dir" "/"
test_tab_complete "walt node config $node ram=4G netset" "up="
test_tabtab_complete "walt node reboot my-nodes" "my-nodes   my-nodes,"
test_tabtab_complete "walt node config $node " "cpu.cores=    disks=        kexec.allow=  netsetup=     networks=     ram="
EOF

    # cleanup
    rm -rf $tmp_dir
    walt node remove $node
    walt image remove $image
}
