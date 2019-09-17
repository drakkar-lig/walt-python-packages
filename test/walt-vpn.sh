define_test "walt vpn monitor" as {
    random_mac=$(printf '00:60:2f:%02x:%02x:%02x' $[RANDOM%256] $[RANDOM%256] $[RANDOM%256])

    # fake a new VPN device grant request
    {
        sleep 3
        timeout -s INT 10 walt-vpn-auth-tool "$random_mac"
    } &

    expect << EOF
set timeout 5
spawn walt vpn monitor
expect {
    "$random_mac"  { }
    timeout { puts "timeout: 'walt vpn monitor' did not detect VPN grant request!"; exit 1 }
}
expect ": \$"
send "y\r"
expect "Device access was granted.\$"
sleep 1
# send ctrl-c
send "\003"
EOF
}
