source $TESTS_DIR/includes/common.sh

SQL_CONFIGURED_SWITCH="""\
select d.name, (d.conf->'lldp.explore')::text
from devices d
where d.conf->'snmp.version' is not NULL
  and d.conf->'snmp.community' is not NULL
  and d.type = 'switch'
limit 1;
"""

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
    output="$(
        psql walt -t -c "$SQL_CONFIGURED_SWITCH" | tr -d '|'
    )"

    if [ "$output" = "" ]
    then
        echo "did not find a switch to run this test on" >&2
        return 1
    fi

    set -- $output
    name="$1"
    orig_lldp_explore="$2"
    other_lldp_explore="$(negate $orig_lldp_explore)"

    # try to change setting, then restore it
    walt device config "$name" lldp.explore=$other_lldp_explore

    # verify it is really updated
    walt device config "$name" | grep "lldp.explore=" | grep "$other_lldp_explore"

    # restore
    walt device config "$name" lldp.explore=$orig_lldp_explore
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
