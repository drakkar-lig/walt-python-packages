source $BATS_TEST_DIRNAME/common.sh

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

@test "walt device config" {
    set -- $(
        psql walt -t -c "$SQL_NODE_AND_NETSETUP" | tr -d '|'
    )

    if [ "$1" == "" ]
    then
        skip "did not find a node to run this test on"
    fi

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
    walt device config "$name" netsetup $other_netsetup && {
        # verify it is really updated
        num=$(walt node show --all | grep "^$name " | grep -w "$other_netsetup" | wc -l)
        [ $num -eq 1 ]
    } && \
    walt device config "$name" netsetup $netsetup
}

@test "walt device admin" {

    set -- $(
        psql walt -t -c "$SQL_CONFIGURED_SWITCH" | tr -d '|'
    )

    if [ "$1" == "" ]
    then
        skip "did not find a switch to run this test on"
    fi

    name="$1"
    shift

    print_admin_responses "$@" | walt device admin "$name"
}

@test "walt device ping" {
    # here, we just check that the command times out (return code 124).
    test_timeout 3 walt device ping walt-server || [ "$?" = "124" ]
}

@test "walt device rescan" {
    run walt device rescan
    [ "$status" -eq 0 ]
}

@test "walt device tree" {
    run walt device tree
    [ "$status" -eq 0 ]
}

@test "walt device show" {
    run walt device show
    [ "$status" -eq 0 ]
}

@test "walt device rename" {
    set -- $(
        psql walt -t -c "$SQL_ONE_DEVICE_NAME" | tr -d '|'
    )

    if [ "$1" == "" ]
    then
        skip "did not find a device to run this test on"
    fi

    name="$1"
    newname="$1-test-$$"

    run walt device rename "$name" "$newname"
    [ "$status" -eq 0 ] || return 1

    # restore
    walt device rename "$newname" "$name"
}
