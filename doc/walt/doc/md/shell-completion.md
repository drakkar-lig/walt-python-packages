
# Shell completion setup (bash and zsh)

Completion scripts for bash and zsh are automatically setup and updated on
the server, when installing or upgrading it.

However, if you use the walt client tool on another machine, the following
tips are useful.


## Bash completion setup on a client machine

The command `walt advanced dump-bash-autocomplete` can generate a completion
script.

For instance, to enable completion for all users of a debian-based client
machine, ensure the package `bash-completion` is installed and run as root:
```
$ mkdir -p /etc/bash_completion.d
$ walt advanced dump-bash-autocomplete > /etc/bash_completion.d/walt
```

Alternatively, if you have no root access, this will enable bash completion
for your user only on this debian-based machine:
```
$ mkdir -p $HOME/.local/share/bash-completion/completions
$ cd $HOME/.local/share/bash-completion/completions
$ walt advanced dump-bash-autocomplete > walt
```

Then log out and log in again.


## Zsh completion setup on a client machine

The command `walt advanced dump-zsh-autocomplete` can generate a completion
script.

For instance, to enable completion for all users of a debian-based client
machine, run as root:
```
$ mkdir -p /usr/local/share/zsh/site-functions
$ walt advanced dump-zsh-autocomplete > \
        /usr/local/share/zsh/site-functions/_walt
```

Then users should log out and log in again.
