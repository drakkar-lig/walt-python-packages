CURL_PREFER_HEADER="Prefer: errors=text-only"
source $TESTS_DIR/includes/common.sh

do_curl() {
    fake_requester_ip="$1"
    path="$2"
    shift 2
    server_ip=$(get_walt_server_ip)
    url="http://${server_ip}/walt-vpn/${path}"
    url="${url}?fake_requester_ip=${fake_requester_ip}"
    if ! curl_out="$(curl --fail-with-body \
                      -H "$CURL_PREFER_HEADER" \
                      --no-progress-meter \
                      "$@" "$url")"
    then
        echo "$curl_out" >&2
        return 1
    else
        echo "$curl_out"
    fi
}

define_test "walt vpn enrollment" as {
    echo "Preparation work: create a fake rpi-5-b node."
    dev_name="fake-rpi5b-$$"
    info=$(create_fake_device "$dev_name" "walt.node.rpi-5-b")
    dev_ip=$(echo "$info" | grep "^ip:" | awk '{print $2}')

    # walk through the enrollment steps
    ssh_entrypoint="$(do_curl "$dev_ip" "node-conf/ssh-entrypoint")"
    http_entrypoint="$(do_curl "$dev_ip" "node-conf/http-entrypoint")"
    boot_mode="$(do_curl "$dev_ip" "node-conf/boot-mode")"

    if [ "$ssh_entrypoint" = "" -o \
         "$http_entrypoint" = "" -o \
         "$boot_mode" = "" ]
    then
        walt device forget "$dev_name"
        skip_test "VPN not fully configured on server"
        return 1
    fi

    tmpdir=$(mktemp -d)
    cd "$tmpdir"
    echo "** Generating SSH keypair"
    ssh-keygen -q -N '' -t ecdsa -b 384 -f "id_walt_vpn"
    echo "** Sending enrollment request"
    do_curl "$dev_ip" enroll -F "ssh-pubkey=@-" >/dev/null < "id_walt_vpn.pub"
    echo "** Fetching pubkey signed by VPN CA"
    do_curl "$dev_ip" node-conf/ssh-pubkey-cert > "id_walt_vpn-cert.pub"
    rm "id_walt_vpn.pub"  # no longer needed
    echo "** Fetching SSH VPN entrypoint host keys"
    do_curl "$dev_ip" node-conf/ssh-entrypoint-host-keys > "known_hosts"
    echo "** Fetching other WalT VPN parameters"
    for param in public.pem http-path vpn-mac
    do
        do_curl "$dev_ip" "node-conf/${param}" > "${param}"
    done
    # test if we got those params properly
    for f in id_walt_vpn-cert.pub known_hosts public.pem http-path vpn-mac
    do
        [ -s "$f" ]   # check file is not empty
    done

    # retrieve and save certid for next tests
    vpnmac=$(cat vpn-mac)
    query="select certid from vpnauth where vpnmac = '${vpnmac}';"
    set -- $(psql --no-psqlrc walt -t -c "$query")
    echo -n "$1" > /tmp/test-certid

    # cleanup
    walt device forget "$dev_name"
    cd -
    rm -rf $tmpdir
}

define_test "walt-vpn-admin ssh-ep-setup" as {
    tmpdir=$(mktemp -d)
    cd "$tmpdir"
    expect << EOF
set timeout 5
spawn walt-vpn-admin
expect {
    "generate a VPN SSH entrypoint setup script"  { }
    timeout { puts "timeout: 'walt-vpn-admin' did not print the expected menu entry!"; exit 1 }
}
send "\r"
expect "ssh-ep-setup.sh"
send "\r"   ;# return to main menu
send "BBBB" ;# down four times
send "\r"   ;# quit this screen
EOF
    [ -s "ssh-ep-setup.sh" ] && rm -f "ssh-ep-setup.sh"
    cd -
    rm -rf "$tmpdir"
}


get_test_certid() {
    [ -f "/tmp/test-certid" ] || skip_test "walt vpn enrollment failed"
    cat /tmp/test-certid
}

define_test "walt-vpn-admin list-valid-keys" as {
    certid=$(get_test_certid)
    expect << EOF
set timeout 5
spawn walt-vpn-admin
expect {
    "list valid authentication keys"  { }
    timeout { puts "timeout: 'walt-vpn-admin' did not print the expected menu entry!"; exit 1 }
}
send "B"    ;# down once (2nd menu entry)
send "\r"
expect "${certid}"
send "\r"   ;# return to main menu
send "BBBB" ;# down four times
send "\r"   ;# quit this screen
EOF
}

define_test "walt-vpn-admin revoke-key" as {
    certid=$(get_test_certid)
    expect << EOF
set timeout 5
spawn walt-vpn-admin
expect {
    "revoke an authentication key"  { }
    timeout { puts "timeout: 'walt-vpn-admin' did not print the expected menu entry!"; exit 1 }
}
send "BBB"    ;# down 3 times (4th menu entry)
send "\r"
expect "Enter the key you want to revoke"
send "${certid}\r"
expect "Done"
send "\r"   ;# return to main menu
send "BBBB" ;# down four times
send "\r"   ;# quit this screen
EOF
}

define_test "walt-vpn-admin list-revoked-keys" as {
    certid=$(get_test_certid)
    expect << EOF
set timeout 5
spawn walt-vpn-admin
expect {
    "list revoked authentication keys"  { }
    timeout { puts "timeout: 'walt-vpn-admin' did not print the expected menu entry!"; exit 1 }
}
send "BB"    ;# down twice (3rd menu entry)
send "\r"
expect "${certid}"
send "\r"   ;# return to main menu
send "BBBB" ;# down four times
send "\r"   ;# quit this screen
EOF

    # cleanup since this is the last test
    query="delete from vpnauth where certid = '${certid}';"
    psql --no-psqlrc walt -t -c "$query"
    rm /tmp/test-certid
}

