
TEST_IMAGE_URL='hub:eduble/pc-x86-64-test-suite'
# When the blocking process is involved, server api calls may last
# longer because the blocking process may be busy with something else
# (e.g. automatic hard-reboots or powersave handling).
# So we define a rather large timeout value.
EXPECT_TIMEOUT_BLOCKING_INVOLVED=30

test_suite_image() {
    if [ ! -e /tmp/test_suite_image ]
    then
        echo pc-x86-64-test-suite-$$ > /tmp/test_suite_image
    fi
    cat /tmp/test_suite_image
}

image_exists() {
    walt image show | grep "$1 "
}

test_suite_node() {
    if [ ! -e /tmp/test_suite_node ]
    then
        echo testnode-$$ > /tmp/test_suite_node
    fi
    cat /tmp/test_suite_node
}

node_exists() {
    walt node show --all | grep "$1 "
}

test_walt_cp() {
    category="$1"
    target="$2"
    tempdir=$(mktemp -d)
    checkfile=$(mktemp -u)
    echo $$ > $tempdir/testfile
    walt $category cp $tempdir $target:/root/
    walt $category cp $target:/root/$(basename $tempdir)/testfile $checkfile
    diff $tempdir/testfile $checkfile
    rm -rf $tempdir $checkfile
}

test_walt_shell() {
    category="$1"
    target="$2"
    which expect || {
        echo 'This test requires the "expect" command.' >&2
        return 1
    }

    if [ "$category" = "node" ]
    then
        expect << EOF
set timeout 5
spawn walt node shell $target
expect {
    "# \$"  { }
    timeout { puts "timeout: 'walt node shell' did not show the prompt!"; exit 1 }
}
send "echo ok > /root/test\r"
expect "# \$"
send "exit\r"
expect "closed.\$"
EOF
    else    # image
        expect << EOF
set timeout $EXPECT_TIMEOUT_BLOCKING_INVOLVED
spawn walt image shell $target
expect {
    "# \$"  { }
    timeout { puts "timeout: 'walt image shell' did not show the prompt!"; exit 1 }
}
send "echo ok > /root/test\r"
expect "# \$"
send "exit\r"
expect ": \$"
send "\r"
send "y\r"
expect "updated.\$"
EOF
    fi
    checkfile=$(mktemp -u)
    walt $category cp $target:/root/test $checkfile
    out=$(cat $checkfile)
    rm -f $checkfile
    [ "$out" = "ok" ]
}

test_walt_console() {
    node="$1"
    which expect || {
        echo 'This test requires the "expect" command.' >&2
        return 1
    }

    expect << EOF
set timeout 5
spawn walt node console $node
# define error management
expect_before {
    timeout { puts "timeout: 'walt node console' did not respond properly!"; exit 1 }
    eof     { puts "eof": 'walt node console' ended unexpectedly!"; exit 1 }
}
# wait for welcome message
expect "abort: "
# pass welcome message
send "\r"
sleep 1
# send <enter> to trigger the credential prompt
send "\r"
# wait for credential prompt
expect "$node login: "
# send ctrl-a d
send "\x01"; sleep 1; send "d"
expect "Disconnected from console."
EOF
}

get_walt_server_ip() {
    which jq >/dev/null || {
        skip_test 'requires the "jq" command'
    }

    ip -4 -j addr show dev walt-net | \
        jq -r .[0].addr_info[0].local
}

end_of_mac() {
    set -- $(echo "$1" | tr ':' ' ')
    echo $4$5$6
}

create_fake_device() {
    # We first create the fake device as a virtual node, retrieve
    # its ip and mac, then remove this virtual node and recreate
    # it as an unknown device using walt-dhcp-event.
    dev_name="$1"
    vci="$2"
    walt node create "$dev_name"
    ip_mac="$(
        psql --no-psqlrc walt -t \
            -c "select ip, mac from devices where name='$dev_name'" | tr -d '|'
    )"
    set -- $ip_mac
    ip=$1
    mac=$2
    mac_suffix=$(end_of_mac $mac)
    walt node remove "$dev_name"
    walt-dhcp-event commit --force-name \
        "$vci" "" $ip $mac "$dev_name" "0" "unknown"
    echo "ip: $ip"
}
