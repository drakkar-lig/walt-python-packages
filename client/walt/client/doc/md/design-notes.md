
# Scope and design notes

Generally speaking, a given WalT platform is not designed to serve a large userbase; it is rather designed as **a tool for teammates**.
If many users want to use WalT, then **each team should install its own private WalT platform**.
Moreover, the WalT platform is not supposed to be directly accessible from the internet.

This design choice as important implications:
* All users have full control over the platform; this includes plugging or unplugging nodes and network switches for instance.
* We consider that users will be kind with others, and the plaform itself enforces very few usage restrictions. If a command is likely to disrupt the work of others, the platform will not prevent you from executing it, but it will ask you for confirmation. The concept of "node ownership" for instance follows this general principle (see [`walt help show node-ownership`](node-ownership.md)).
* WalT is very friendly for new users: they do not need a registration procedure and they immediately have access to the platform resources (no reservation system).
* Since the platform is not supposed to be directly accessible from internet, WalT only implements a thin layer of security features (e.g., for VPN).
* Compared to a public platform, a private WalT platform can better fit some use cases, including industrial testbeds, because of the possible industrial secrets involved.

