
# Shell completion setup (bash and zsh)

Completion scripts for bash and zsh are **automatically setup and updated on
the server**, when installing or upgrading it.

However, if you use the walt client tool on another machine, you will need
one more setup step to enable shell completion, as described below.


## Status of shell completion setup

When running `walt` command with no arguments, among other information
the current status of shell completion is displayed (i.e., `up-to-date`
or not).

Note however, for this information to be refreshed after you install
or upgrade the completion script (as shown below), you need:
* to log out and log in again. (`bash` case)
* to log out, log in again, and trigger the completion at least once,
  e.g. by typing `walt <tab><tab>`. (`zsh` case)


## Shell completion setup or upgrade on a client machine

### Bash completion setup or upgrade

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

For an upgrade, you can use the same commands to overwrite the outdated
completion script.

In any case, log out and log in again.


### Zsh completion setup or upgrade

The command `walt advanced dump-zsh-autocomplete` can generate a completion
script.

For instance, to enable completion for all users of a debian-based client
machine, run as root:
```
$ mkdir -p /usr/local/share/zsh/site-functions
$ walt advanced dump-zsh-autocomplete > \
        /usr/local/share/zsh/site-functions/_walt
```

For an upgrade, you can use the same command to overwrite the outdated
completion script.

In any case, users should then log out and log in again.
