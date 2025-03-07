# Using the serial port of a Raspberry Pi

Debugging the early bootup steps of a WalT node is sometimes tricky.
Connecting to a serial port allows to view the bootloader log messages and can greatly ease this work.
This section explains how to connect to the serial port of a Raspberry Pi board.


## Summary

| Model | Serial connector     | Works well |
|-------|----------------------|------------|
| B     | GPIO pins (1)        | Yes        |
| B+    | GPIO pins (1)        | Yes        |
| 2B    | GPIO pins (1)        | Yes        |
| 3B    | GPIO pins (1)        | No (2)     |
| 3B+   | GPIO pins (1)        | No (2)     |
| 4B    | GPIO pins (1)        | No (2)     |
| 5B    | JST-SH connector (3) | Yes        |

Notes:
1. See "Older models" / "Position of GPIO pins" below.
2. See "Older models" / "Note about the mini-UART" below.
3. See "Raspberry Pi 5" / "Connecting the Debug Probe" below.


## Raspberry Pi 5

The serial connector of the Raspberry Pi 5 is a dedicated JST-SH 3-pin connector.
We recommend purchasing the "Raspberry Pi Debug Probe" for connecting to it.


### Position of the JST connector

The UART JST connector is between the two micro-HDMI connectors of the Rpi 5B board.


### Connecting the Debug Probe

The Raspberry Pi Debug Probe is sold with 4 cables included in the package.
You must use the "3-pin JST-SH to 3-pin JST-SH cable" to connect the Debug Probe
to the UART JST connector of the Rpi 5 board, as shown in the following figure.
Don't try to seat the JST connectors too much (both on the Debug Probe and
on the Raspberry Pi board).

Obviously you must also use the provided USB cable to connect the Debug Probe
to your laptop.

```

                            Your laptop

---------------------------|USB|----|USB|----|USB|---------------
                            | |
                            ┆ ┆
                            | |
                        ---|USB|----
                       |            |
                       |   Debug    |
                       |   Probe    |
                       |            |
                       |  U     D   |
                       | [╷╷]  [  ] |
                        --||--------
                          ||
              (grey side) ┆┆ (red side of the cable)
                          ||
                    hdmi  ||  hdmi      usb-c
 -------------------|  |--||--|  |------|   |---
|                   |  | [╵╵] |  |      |   |   |
|                    ‾‾  uart  ‾‾        ‾‾‾    |
|                                               |
|                Raspberry Pi 5B board          |
|                                               |

```

When the Debug Probe is connected on a Linux machine, a device /dev/ttyACM0
(or perhaps ttyACM1 if ttyACM0 is already allocated) appears:
```
$ sudo dmesg | grep ttyACM
[   71.635627] cdc_acm 1-1:1.1: ttyACM0: USB ACM device
$
```

You can then use your usual software (e.g., minicom) for interacting with this
serial device, with communication parameters set as 115200 8N1.


## Older models

### Note about the mini-UART

In their default configuration, 3B 3B+ and 4B models use a limited mini-UART chip
for serial communication, so you may face problems such as missed characters on
input.

If the problem you are facing is not specific to a given model, then we recommend
to use another model instead.

It is also possible to reconfigure the board to use its regular PL011 chip instead.
In the default configuration, this chip is used for bluetooth.
See https://www.raspberrypi.com/documentation/computers/configuration.html#configure-uarts.


### Position of GPIO pins

The serial connection should be made on the 3rd, 4th and 5th GPIO pins of the upper line of pins
(the line of pins closest to the edge of the board, see figure).

```
   BYO
 --↓↓↓------------------------
|::::::::::::::::::::
|
|    Raspberry Pi board
|

```


B stands for Black, it is the Ground pin.
Y stands for Yellow, it is the TX pin of the board.
O stands for Orange, it is the RX pin of the board.


### Connecting a TTL-232R-3V3 cable

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
|    Raspberry Pi board
|

```

When the usb-A connector of the TTL-232R-3V3 cable is connected on a Linux machine, a device /dev/ttyUSB0
(or perhaps ttyUSB1 if ttyUSB0 is already allocated) appears:
```
$ sudo dmesg | grep ttyUSB
[    3.168625] usb 2-2: FTDI USB Serial Device converter now attached to ttyUSB0
$
```

You can then use your usual software (e.g., minicom) for interacting with this
serial device, with communication parameters set as 115200 8N1.
