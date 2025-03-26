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

define_test "walt device config" as {
    cat << EOF
Preparation work: create a fake unknown device.
EOF
    dev_name="unknown-device-$$"
    create_fake_device "$dev_name" ""

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
        psql --no-psqlrc walt -t -c "$SQL_ONE_DEVICE_NAME" | tr -d '|'
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
        skip_test 'requires the "wget" command'
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

