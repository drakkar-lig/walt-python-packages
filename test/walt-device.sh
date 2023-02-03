source $TESTS_DIR/includes/common.sh

SQL_ONE_DEVICE_NAME="""\
select d.name
from devices d
limit 1;
"""

negate() {
    if [ "$1" = "true" ]
    then
        echo "false"
    else
        echo "true"
    fi
}

end_of_mac() {
    set -- $(echo "$1" | tr ':' ' ')
    echo $4$5$6
}

define_test "walt device config" as {
    cat << EOF
Preparation work: we want to create an unknown device in database.
We will first create it as a virtual node, retrieve
its ip and mac, then remove this virtual node and recreate
it as an unknown device using walt-dhcp-event.
EOF
    dev_name="unknown-device-$$"
    walt node create "$dev_name"
    ip_mac="$(
        psql walt -t -c "select ip, mac from devices where name='$dev_name'" | tr -d '|'
    )"
    set -- $ip_mac
    ip=$1
    mac=$2
    mac_suffix=$(end_of_mac $mac)
    walt node remove "$dev_name"
    walt-dhcp-event commit "" "" $ip $mac "unknown"
    dev_name="unknown-$mac_suffix"
    sleep 2

    # real tests...

    # turn the unknown device to a switch
    walt device config "$dev_name" type='switch'
    dev_name="switch-$mac_suffix" # server should have renamed it like this

    # try to change settings
    walt device config "$dev_name" lldp.explore=true snmp.community='private' snmp.version=2

    # verify they were really updated
    walt device config "$dev_name" | grep "lldp.explore=" | grep "true"

    # cleanup
    walt device forget "$dev_name"
}

define_test "walt device ping" as {
    # here, we just check that the command times out (return code 124).
    timeout -s INT 3 walt device ping walt-server || [ "$?" = "124" ]
}

define_test "walt device rescan" as {
    walt device rescan
}

define_test "walt device tree" as {
    walt device tree
}

define_test "walt device show" as {
    walt device show
}

define_test "walt device rename" as {
    output="$(
        psql walt -t -c "$SQL_ONE_DEVICE_NAME" | tr -d '|'
    )"

    if [ "$output" = "" ]
    then
        echo "did not find a device to run this test on" >&2
        return 1
    fi

    set -- $output
    name="$1"
    newname="$1-test-$$"

    walt device rename "$name" "$newname"

    # restore
    walt device rename "$newname" "$name"
}

define_test "walt device forget (on non existing device)" as {
    walt device forget eazgzaezgeriogahregu
}

define_test "walt device shell (on non existing device)" as {
    { walt device shell eazgzaezgeriogahregu 2>&1 || true; } | grep "No device with name"
}

define_test "walt device expose" as {

    which wget || {
        echo 'This test requires the "wget" command.' >&2
        return 1
    }

    # use walt device expose to redirect port localhost:8083 to <server-ip>:80
    {
        timeout -s INT 5 walt device expose "walt-server" 80 8083
    } &

    # check that running wget we get the html page returned by walt-server-httpd
    sleep 2
    echo "NOTE: this test also checks walt-server-httpd is responding."
    wget -q -O - http://localhost:8083/ | grep "WalT server HTTP service"
}

