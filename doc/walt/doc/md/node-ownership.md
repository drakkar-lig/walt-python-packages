
# Node ownership

The concept of node ownership implemented in WalT helps users to share platform resources when using the platform at the same time.
As shown below, the platform usage remains very flexible (see [`walt help show design-notes`](design-notes.md) for related concepts).


## "Acquiring" and "Releasing" nodes

A node is considered to be used by 0 or 1 user at a given time. If 0, the node appears as "free". If 1, we consider that this user **owns** the node.
Users can get or release ownership of a (set of) node(s) by using commands `walt node acquire <node(s)>` and `walt node release <node(s)>`.

When running `walt node show` with no option, only the nodes one owns are listed.
When running `walt node show --all`, free ones and those of other users are listed too.

After a node is released, it appears as "free" for all users.
At the end of an experiment, a good practice is to release all the nodes one owns:
```
$ walt node release my-nodes
```
(`my-nodes` is a keyword, cf. [`walt help show device-sets`](device-sets.md) for details.)

Releasing PoE-powered nodes also allows automatic power savings (cf. [`walt help show powersave`](powersave.md)).

Users usually acquire nodes from the set of "free" ones. However, a teammate may have forgotten to release some nodes.
In this case, one can still acquire such nodes owned by someone else but a confirmation is required.


## Other information about free nodes

For other information about free nodes, such as how to change the OS image they boot, or letting WALT save power by turning them off after a delay, see [`walt help show free-nodes`](free-nodes.md).
