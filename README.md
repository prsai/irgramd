# irgramd - IRC <-> Telegram Gateway

irgramd is a gateway that allows connecting from an [IRC] client to
[Telegram] as a regular user (not bot).

irgramd is written in [python] (version 3), it acts as an IRC server
where an IRC client can connect and on the other side it's a Telegram client
using the [Telethon] library.

**[irgramd primary repository] is in [darcs] version control system, github
is used as [project management and secondary repository]**

**irgramd was forked from [pbui/irtelegramd], was heavily modified and
currently is a project on its own**

**irgramd is under active development in alpha state, though usable, several
planned features are not implemented yet**

## How it works

Configure your IRC client to connect to irgramd (running on the same host or
on a remote host) then you will see in your IRC client the Telegram groups
as IRC channels and Telegram users as IRC users, if you send a message to a
user or channel in IRC it will go to the corresponding user or group in
Telegram, and the same from Telegram to IRC.

The users on Telegram using the official or other clients will see you with
your regular Telegram user account and will be indistinguishable for them
whether you are using irgramd or another Telegram client.

Several IRC clients can connect to irgramd but they will see the same
Telegram account, this allows connecting to the same Telegram account from
different IRC clients on different locations or devices, so one irgramd
instance only connects to one Telegram account, if you want to connect to
several Telegram accounts you will need to run several irgramd instances.

## Features

- Channels, groups and private chats
- Users and channels mapped in IRC
- Messages (receive, send)
- Media in messages (receive, download)
- Replies (receive, send)
- Forwards (receive)
- Deletions (receive, do)
- Editions (receive, do)
- Reactions (receive)
- Dialogs management
- History
- Authentication and TLS for IRC
- Multiple connections from IRC

## Requirements

- [python] (>= v3.9)
- [telethon] (tested with v1.28.5)
- [tornado] (tested with v6.1.0)
- [aioconsole] (tested with v0.6.1)
- [pyPAM] (optional, tested with v0.4.2-13.4 from deb, [legacy web](https://web.archive.org/web/20110316070059/http://www.pangalactic.org/PyPAM/))

## Instalation

### From darcs

    darcs clone https://src.presi.org/repos/darcs/irgramd
    chmod +x irgramd/irgramd

### From git

    git clone https://github.com/prsai/irgramd.git
    chmod +x irgramd/irgramd

## Configuration

From irgramd directory `./irgramd --help` will show all configuration
options available, these options can be used directy in the command line or
in a file.

When used in command line the separator is `-` (dash) with two leading
dashes, example: `--api-hash`.

When used in a file the separator is `_` (underscore) without two leading
dashes nor underscores, example: `api_hash`. The syntax of this file is just
Python so strings are surrounded by quotes (`'`) and lists by brackets (`[]`).

A sample of the configuration file is provided, copy it to the default
configuration location:

    mkdir -p  ~/.config/irgramd
    cp irgramd/irgramdrc.sample ~/.config/irgramd/irgramdrc

And modified it with your API IDs and preferences.

## Usage

From irgramd directory, in foreground:

    ./irgramd

In background (without logs):

    ./irgramd --logging=none &

## Notes

PAM authentication: it allows to authenticate IRC users from the system in
Unix/Linux. The user that executes irgramd must have permissions to use PAM
(e.g. in Linux be in the shadow group or equivalent). The dependency is
totally optional, if not used, the module pyPAM is not needed.

## License

Copyright (c) 2019 Peter Bui <pbui@bx612.space>  
Copyright (c) 2020-2023 E. Bosch <presidev@AT@gmail.com>

Use of this source code is governed by a MIT style license that
can be found in the LICENSE file included in this project.

[IRC]: https://en.wikipedia.org/wiki/Internet_Relay_Chat
[Telegram]: https://telegram.org/
[python]: https://www.python.org/
[Telethon]: https://github.com/LonamiWebs/Telethon
[irgramd primary repository]: https://src.presi.org/darcs/irgramd
[darcs]: http://darcs.net
[project management and secondary repository]: https://github.com/prsai/irgramd
[pbui/irtelegramd]: https://github.com/pbui/irtelegramd
[python]: https://www.python.org
[tornado]: https://www.tornadoweb.org
[aioconsole]: https://github.com/vxgmichel/aioconsole
[pyPAM]: https://packages.debian.org/bullseye/python3-pam
