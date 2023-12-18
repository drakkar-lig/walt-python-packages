# Using the serial port of a Raspberry Pi

Debugging the early bootup steps of a WalT node is sometimes tricky.
Connecting to a serial port allows to view the bootloader log messages and can greatly ease this work.
This section explains how to connect to the serial port of a Raspberry Pi board.


## Preliminary note

First, if you own an old board model (2B or earlier) and the problem you are facing is not specific
to a newer model, then we recommend using it.

In their default configuration, newer models (3B and later) use their full-featured PL011 chip to
communicate with the bluetooth controller instead of managing the serial port. This leaves
the serial port management to a mini-UART, which is a quite limited chip. It may miss characters
at high baudrates. It is however possible to reconfigure the board to use the PL011 chip for the serial
port (see https://www.raspberrypi.com/documentation/computers/configuration.html#configuring-uarts).


## Position of GPIO pins

The serial connection should be made on the 3rd, 4th and 5th GPIO pins of the upper line of pins
(the line of pins closest to the edge of the board, see figure).

```
   BYO
 --↓↓↓------------------------
|::::::::::::::::::::
|
|    Raspberry pi board
|

```


B stands for Black, it is the Ground pin.
Y stands for Yellow, it is the TX pin of the board.
O stands for Orange, it is the RX pin of the board.


## Connecting a TTL-232R-3V3 cable

Obviously, the RX pin of the board must be connected to the TX pin of the TTL cable, and vice versa.
We also need a ribbon cable.

The TTL-232R-3V3 has 6 colored cables, Black, Maroon, Red, Orange, Yellow and Green. We will need
only the Black, Orange, and Yellow ones, as shown on the second figure below.
Take care of the different order on the two ends of the ribbon cable (Orange and Yellow are inverted).

```
   usb-A    ^
    ||      |
    ||      | TTL-232R-3V3
   /  \     | cable
  /    \    |
  BMROYG    v
  B  OY     ^
  \   /     |
   |||      | ribbon cable
   |||      |
   BYO      v
 --↓↓↓------------------------
|::::::::::::::::::::
|
|    Raspberry pi board
|

```

When the usb-A connector of the TTL-232R-3V3 cable is connected on a Linux machine, a device /dev/ttyUSB0
(or perhaps ttyUSB1 if ttyUSB0 is already allocated) appears:
```
$ dmesg | grep ttyUSB
[    3.168625] usb 2-2: FTDI USB Serial Device converter now attached to ttyUSB0
$
```

You can then use our usual software (e.g., minicom) for interacting with this serial device, with
communication parameters set as 115200 8N1.
