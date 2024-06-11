#!/usr/bin/python
# A Wake on LAN program that allows you to send magic packets over the Internet
# credits from https://www.github.com/rschuetzler

import socket
import struct
import ipaddress

class Waker():
    def __init__(self, walt_network):
        self.broadcast_ipv4 = str(ipaddress.IPv4Network(walt_network).broadcast_address)


    def makeMagicPacket(self, macAddress):
        # Take the entered MAC address and format it to be sent via socket
        splitMac = str.split(macAddress,':')
    
        # Pack together the sections of the MAC address as binary hex
        hexMac = struct.pack('BBBBBB', int(splitMac[0], 16),
                             int(splitMac[1], 16),
                             int(splitMac[2], 16),
                             int(splitMac[3], 16),
                             int(splitMac[4], 16),
                             int(splitMac[5], 16))
    
        #create the magic packet from MAC address
        self.packet = b'\xff' * 6 + hexMac * 16
    
    def sendPacket(self, packet, destIP, destPort = 7):
        try:
            # Create the socket connection and send the packet
            s=socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
            # send a broadcast, 
            # safer than relying on a destIP which will possibly 
            # not be presented in the switch's ARP table anymore
            destIP="ff02::1" 
            s.sendto(packet,(destIP,destPort))
            s.close()
        except: # if ipv6 not supported on the server node
            s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            # send a broadcast, 
            # safer than relying on a destIP which will possibly 
            # not be presented in the switch's ARP table anymore
            
            # find a mean to know the walt server ip within the walt net or 
            # find a way to broadcast on an interface
            destIP=self.broadcast_ipv4
            s.sendto(packet,(destIP,destPort))
            s.close()

        
    def wake(self, macAddress, destIP, destPort=7):
        self.makeMagicPacket(macAddress)
        self.sendPacket(self.packet, destIP, destPort)