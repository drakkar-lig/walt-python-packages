
# Shell completion setup (bash)

Command `walt advanced dump-bash-autocomplete` can generate a bash auto-completion script.

To enable completion for all users, run as root:
```
$ walt advanced dump-bash-autocomplete > /etc/bash_completion.d/walt
```

Alternatively, if you have no root access, this will enable bash completion for your user only:
```
$ mkdir -p $HOME/.local/share/bash-completion/completions
$ cd $HOME/.local/share/bash-completion/completions
$ walt advanced dump-bash-autocomplete > walt
```

Then log out and log in again.
