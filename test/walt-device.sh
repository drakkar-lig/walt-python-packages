source $TESTS_DIR/includes/common.sh

SQL_CONFIGURED_SWITCH="""\
select d.name, s.lldp_explore, s.poe_reboot_nodes, s.snmp_conf::json -> 'version', s.snmp_conf::json ->> 'community'
from switches s, devices d
where s.snmp_conf is not null
  and s.mac = d.mac
limit 1;
"""

SQL_NODE_AND_NETSETUP="""\
select d.name, n.netsetup
from nodes n, devices d
where n.mac = d.mac
limit 1;
"""

SQL_ONE_DEVICE_NAME="""\
select d.name
from devices d
limit 1;
"""

print_admin_responses() {
    lldp_explore="$1"
    poe_reboot_nodes="$2"
    version="$3"
    community="$4"

    # Notes:
    # - PoE questions are only asked if LLDP is enabled
    # - SNMP conf is only asked if LLDP is enabled
    # - There is a final confirm requested at the end

    if [ "$lldp_explore" = "t" ]    # t == true
    then
        echo y

        if [ "$poe_reboot_nodes" = "t" ]    # t == true
        then
            echo y
            echo y
        else
            echo n
        fi

        echo $version
        echo $community
    else
        echo n
    fi

    echo y
}

define_test "walt device config" as {
    output="$(
        psql walt -t -c "$SQL_NODE_AND_NETSETUP" | tr -d '|'
    )"

    if [ "$output" = "" ]
    then
        echo "did not find a node to run this test on" >&2
        return 1
    fi

    set -- $output
    name="$1"

    if [ "$2" = "0" ]
    then
        netsetup="LAN"
        other_netsetup="NAT"
    else
        netsetup="NAT"
        other_netsetup="LAN"
    fi

    # try to change setting, then restore it
    walt device config "$name" netsetup $other_netsetup

    # verify it is really updated
    walt node show --all | grep "^$name " | grep -w "$other_netsetup"

    # restore
    walt device config "$name" netsetup $netsetup
}

define_test "walt device admin" as {
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
    shift

    print_admin_responses "$@" | walt device admin "$name"
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
