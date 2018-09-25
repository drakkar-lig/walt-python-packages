
# Notes about node terminology

## "owning" a node

In WalT terminology, if node `<N>` boots an image created by user `<U>`, we consider that **`<U>` owns `<N>`**.

Thus, if you just started using WalT, **you do not own any node** until you boot an image on one of them (use `walt node boot <node(s)> <image>` for this).

A good practice is, once you are done with your experiment, to boot the default image on them (use `walt node boot my-nodes default` for this), in order to release your **ownership** on these nodes. After you run this, these nodes will appear as **free** to other WalT users.

## specifying a set of nodes

Some commands accept a **set of nodes**:
- `walt node boot`
- `walt node reboot`
- `walt log show`         (see option `--nodes`)

In this case you can specify either:
* the keyword `my-nodes` (this will select the nodes that you own)
* the keyword `all-nodes`
* a coma separated list of nodes (e.g `rpi1,rpi2` or just `rpi1`)
