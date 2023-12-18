# User Tutorial

## Prerequisites

If you want to interact with the docker hub to clone or publish OS images,
you will need an account there. If you do not have one already, you can register
at: https://hub.docker.com/.

## (Optional) Install walt-client

Most users use ssh to connect to the WalT server and use the walt client already
installed there.

If you want to install the WalT client on your own machine (Mac OS X or GNU/Linux)
instead, you can type:

```console
$ sudo pip install walt-client
```

## The `walt` command

`walt` is the entry point of the walt platform management.

You can get an overview of walt subcommands categories by just typing:
```console
$ walt
No sub-command given
------

WalT platform control tool.

Usage:
    walt CATEGORY SUBCOMMAND [args...]

Help about a given category or subcommand:
    walt CATEGORY --help
    walt CATEGORY SUBCOMMAND --help

Help about WalT in general:
    walt help show

Categories:
    advanced  advanced sub-commands
    device    management of WalT platform devices
    help      help sub-commands
    image     management of WalT-nodes operating system images
    log       management of logs
    node      WalT node management sub-commands
$
```
As indicated above, you can get help about a category or about a subcommand using:

```console
$ walt <category> --help
$ walt <category> <command> --help
```

You can also get more detailed information about various aspects of WalT, by typing:

```console
$ walt help show
```

`walt help show` is actually a shortcut of `walt help show help-intro`, because [`help-intro`](help-intro.md) is the default topic displayed.
While using WalT, commands will often print tips about unobvious features, and sometimes direct you to another help topic. For example, to get more information about WalT "shells", you can type:

```console
$ walt help show shells
[...]
$
```

We will now present a little overview of the “essential” commands.

## Exploring the platform

Tree form:

```console
$ walt device tree

main-switch
 ├─2: walt-server
 ├─4: switch-D317-new
 │     ├─3: rpi-D317-2
 │     ├─7: (rpi-demo)
 │     └─8: rpi-D317-1
 ├─5: (rpi-D313-2)
[...]
 └─7: switch-2
       ├─1: rpi-D322-1
[...]
       ├─5: (rpi-kfet-3)
       └─7: switch-3
             ├─1: rpi-D318-1
[...]
$
```

This tree view requires proper LLDP configuration, see [`walt help show switch-install`](switch-install.md).
However, LLDP is an optional feature and the other WalT commands can work without it.

Table form:

```console
$ walt device show

The WalT network contains the following devices:

name         type    mac                ip            switch name  switch port
-----------  ------  -----------------  ------------  -----------  -----------
walt-server  server  00:0e:0c:09:94:4a  192.168.12.1  main-switch  2
switch-D317  switch  6c:b0:ce:0b:33:2c  192.168.12.3  main-switch  4
rpi-D313-2   rpi     b8:27:eb:2e:94:39  192.168.12.6  main-switch  5
switch-D106  switch  28:c6:8e:05:87:5a  192.168.12.2  main-switch  6
[...]

The network position of the following devices is unknown (at least for now):

name        type    mac                ip              reachable
----------  ------  -----------------  --------------  ---------
rpi-new-3   rpi     b8:27:eb:ae:ca:0b  192.168.12.240  NO
rpi-D106-5  rpi     b8:27:eb:77:22:df  192.168.12.111  NO
[...]
$
```

For example, the line of device `rpi-D313-2` indicates it is a raspberry pi (`rpi`), it’s mac and ip address are specified, it is reachable and connected on port `5` of the `main-switch`.

The Raspberry Pi devices listed above are the **nodes** of the platform.

## Having a closer look at the nodes

In order to view the nodes and what they are doing, you can type the following command:

```console
$ walt node show --all

The following nodes are running one of your images:

name           type  image            ip             reachable
-------------  ----  ---------------  -------------  ---------
rpi-D314-1     rpi   rpi-debian       192.168.12.16  yes
rpi-D314-jtag  rpi   rpi-jtag-target  192.168.12.2   yes
[...]

The following nodes are free (they boot a default image):

name           type  ip              reachable
-------------  ----  --------------  ---------
rpi-D106-5     rpi   192.168.12.111  NO
rpi-D301B-4    rpi   192.168.12.164  yes

The following nodes are likely to be used by other users, since you do
not own the image they boot.

name       type  image owner  clonable image link   ip             reachable
---------  ----  -----------  --------------------  -------------  ---------
rpi-D30-1  rpi   zyta         server:zyta/rpi-demo  192.168.12.21  yes
rpi-D31-2  rpi   zyta         server:zyta/rpi-fix   192.168.12.18  NO
[...]
$
```

Three categories of nodes are listed:

1. the nodes that you **own**: in WalT terminology, if node `<N>` boots an image created by user `<U>`, we consider that “`<U>` owns `<N>`”. Thus, if you just started using WalT, this category is empty for now.
2. the nodes that are **free**: they boot a default image (users currently do not use them).
3. the nodes that are **owned by someone else**: the image they are running belongs to another user. If you want to use them, make sure this user is ok. This category is not shown unless you specify the `--all` option.

For more information on this topic, you can type:

```console
$ walt help show node-ownership
```

## The images

In the previous section we’ve seen that a Raspberry Pi was running an image named `rpi-debian`. Let’s have a little explanation.
An image is the operating system a node is running. For example `rpi-debian` is a lightweight Debian OS built for Raspberry Pi.

You can have a look at “your” images with the command:

```console
$ walt image show
Name             Mounted  Created              Ready
---------------  -------  -------------------  -----
rpi-default      False    2016-02-25 17:57:56  True
rpi-default-2    False    2016-04-11 11:01:03  True
rpi-debian-test  True     2016-02-25 17:57:56  True
rpi-debian       True     2016-02-29 10:35:02  True
rpi-openocd      False    2016-03-23 18:06:03  True
$
```

You can see the names of the different images, if they are currently used, their creation date, and whether they are ready (when downloading an image, you will see Ready = False until the download completes).

If you just started using WalT, this list of images is initialized with a set of default images.
You may `clone` other images in order to make them “yours”.

You can `search` for images available for cloning as follows:

```console
$ walt image search jessie
User          Image name       Location           Clonable link
------------  ---------------  -----------        ----------------------------
brunisholz    rpi-debian       walt (other user)  walt:brunisholz/rpi-debian
eduble        rpi-debian-test  docker hub         hub:eduble/rpi-debian-test
onss          rpi-debian       walt (other user)  walt:onss/rpi-debian
waltplatform  rpi-debian       docker hub         hub:waltplatform/rpi-debian
zyta          rpi-debian       docker daemon      docker:zyta/rpi-debian
$
```

WalT images are internally packaged as [Docker](https://www.docker.com/whatisdocker) images.
Listed images may be stored in one of the following locations:

* docker hub (clonable link prefix 'hub:')
* local server, managed by docker daemon (clonable link prefix 'docker:')
* already in walt internal storage (clonable link prefix 'walt:')
* possibly other custom registries configured on the WalT server.

In the third case, only images of other users are listed, since the images you already own do not need to be cloned.

Let’s choose one and clone it:

```console
$ walt image clone walt:brunisholz/rpi-debian
[...]
$
```

After this operation, **your** image `rpi-debian` will be listed when you type `walt image show`.

For now, your image `rpi-debian` is just a clone of image `rpi-debian` of WalT user `brunisholz`. But you can modify it, as we will show below.


## Notes on the usual workflow of WalT users

WalT users usually follow these steps when using WalT:
1. Adapt an OS image (or several ones) to the needs of the experiment.
2. Let nodes run the modified OS images.
3. Monitor the experiment, and possibly interact with nodes if something could not be automated on OS startup. Of course, if something is not working as expected, one might need to return to step 1 for further OS image changes. The experiment monitoring may be automated by using the logging system: see [`walt help show logging`](logging.md).
4. If the experiment gave good results, publish OS images for allowing experiment reproducibility.

It is still possible to modify things while the node is running (i.e., at step 3 instead of step 1).
This is mostly useful in the debugging phase, because step 1 is done in a virtual and limited environment (since the OS is not running on the node yet).
However, for the sake of reproducibility, it is better to have everything set up and automated in the WalT OS image before publishing it.


## Workflow step 1: Customizing your image

*N.B. Operations on the raspberry pi images require ARM emulation on WalT server side. This leads to a slower behavior.*

We will modify our image in order to allow two nodes to play a network ping pong.

A powerful way to modify an image is to use a shell:

```console
$ walt image shell rpi-debian
```

You should now be logged into the image as indicated by the prompt:

```console
root@image-shell:~#
```

Now install `netcat` to set up a lightweight client/server architecture.

```console
root@image-shell:~# apt update
root@image-shell:~# apt install netcat-openbsd
```

Now go to the root directory, create and edit a file named pong.sh. It will be our master server:

```console
root@image-shell:~# cd root/
root@image-shell:~# vim pong.sh
```

And copy the following script:

```bash
#!/bin/bash

# This function is used by netcat to write the appropriate
# response when receiving a specific message
function nc_fct() {
        while read line
        do
                # Here we check if the received message is a
                # "ping" string. If so, we will respond by sending
                # a "pong" message
                if [ $line = "ping" ]
                then
                        # Sleep to avoid heavy useless load
                        sleep 0.1
                        # This actually write into the FIFO
                        echo 'pong'
                        # This is used to print on stderr in order to
                        # monitor and be used with walt-monitor
                        # in order to log the activity.
                        >&2 echo 'pong'
                fi
        done
}

fifo="fifo";
# Create fifo if not created
# This will be used by netcat in order to listen/send messages
[ -p $fifo ] || mkfifo $fifo;

# Start a listening server on port 12345
netcat -l -p 12345 < $fifo | nc_fct 1> $fifo &
```

Make the file executable:

```console
root@image-shell:~# chmod +x pong.sh
```

Now create and edit a file named ping.sh and put it the following code. This will be our client:
```bash
#!/bin/bash

server="$1"
# This function is used by netcat to write the appropriate
# response when receiving a specific message
function nc_fct() {
        while read line
        do
                # Here we check if the received message is a
                # "pong" string. If so, we will respond by sending
                # a "ping" message
                if [ $line = "pong" ]
                then
                        # Sleep to avoid heavy useless load
                        sleep 0.1
                        # This actually write into the FIFO
                        echo 'ping'
                        # This is used to print on stderr in order to
                        # monitor and be used with walt-monitor
                        # in order to log the activity.
                        >&2 echo 'ping'
                fi
        done
}
fifo="fifo";
# Create fifo if not created
# This will be used by netcat in order to listen/send messages
[ -p $fifo ] || mkfifo $fifo;

# Connect to the server running on the other node
netcat "$server" 12345 < $fifo | nc_fct 1> $fifo &
# Send the first ping to initialize the game
echo 'ping' > $fifo
# Print it on stderr in order to see it. We could have use stdout
# on this one.
>&2 echo 'ping'
```
Make the file executable:

```console
root@image-shell:~# chmod +x pong.sh
```

Now exit the container by pressing `CTRL + D` or by typing `exit` in the terminal.
You will be asked for an image name. You can keep `rpi-debian` or save this modified image with a new name.
Let’s call it `rpi-entertainment` for example.

Your freshly customized image should now appear if you type `walt image show`.


## Workflow step 2: Letting nodes boot our modified image

In order to make two of our Raspberry Pi play together, we will have to boot our new image on them.

First, choose two Raspberry Pi we will use:

```console
$ walt node show --all
[...]
The following nodes are free:

name       type  ip             reachable
---------  ----  -------------  ---------
rpi-sw3-3  rpi   192.168.12.16  yes
rpi-sw3-2  rpi   192.168.12.56  yes

[...]
```

We will boot our image on `rpi-sw3-3` and `rpi-sw3-2`, but first we will rename them:

```console
$ walt device rename rpi-sw3-3 rpi-sw3-3-pong
$ walt device rename rpi-sw3-2 rpi-sw3-2-ping
```

> ***Naming Convention:*** *We propose the following naming convention at LIG:* \
> `[shortenedDeviceType]-[geographicalLocation|switchLocation]-[freeSuffix]` \
> *We prefer the geographical (i.e. office name) over switchLocation as it eases maintenance if needed.
> For example a Raspberry Pi located in office D317 could be named:* \
> `rpi-D317-tutorial`

Then we boot nodes:

```console
$ walt node boot rpi-sw3-2-ping,rpi-sw3-3-pong rpi-entertainment
Nodes rpi-sw3-2-ping and rpi-sw3-3-pong will now boot rpi-entertainment.
Nodes rpi-sw3-2-ping and rpi-sw3-3-pong: rebooted ok.
$
```

Nodes are now booting the OS contained in our image.
You could wait until they are fully booted by typing:
```console
$ walt node wait rpi-sw3-2-ping,rpi-sw3-3-pong
```
The command will return when nodes are ready.

## Workflow step 3: Connecting to nodes and monitoring the experiment

Now that our image is running on two nodes, we can connect to them and start the ping pong game.

```console
$ walt node shell rpi-sw3-3-pong
Caution: changes outside /persist will be lost on next node reboot.
Run 'walt help show shells' for more info.

root@rpi-sw3-3-pong:~# ./pong.sh
```

On another terminal connect to the other Raspberry Pi and start the client side.

```console
$ walt node shell rpi-sw3-2-ping
Caution: changes outside /persist will be lost on next node reboot.
Run 'walt help show shells' for more info.

root@rpi-sw3-2-ping:~# ./ping.sh rpi-sw3-3-pong
```

They should start playing ping pong together!

Now if you want to monitor the ping pong logs, you can use the `walt-monitor` command in order to send logs into the walt server.
On the pong server:

```console
root@rpi-sw3-3-pong:~# walt-monitor ./pong.sh
```

On the ping client:

```console
root@rpi-sw3-2-ping:~# walt-monitor ./ping.sh rpi-sw3-3-pong
```

You can then see the logs by typing the `walt log show --realtime` command in another terminal.

## Workflow step 4: Publishing your image

If you are happy with your new `rpi-entertainment` image, you might want to publish it on the docker hub.
This will allow researchers around the world to clone your image and replay your experiment.

Publishing it is as simple as:

```console
$ walt image publish rpi-entertainment
```

## What’s next?

Now you can start doing serious business using walt platform!
