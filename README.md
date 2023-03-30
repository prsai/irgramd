# irgramd - IRC <-> Telegram Gateway

irgramd is a gateway that allows connecting from an [IRC] client to
[Telegram] as a regular user (not bot).

irgramd is written in [python] (version 3), it acts as an IRC server
where an IRC client can connect and on the other side it's a Telegram client
using the [Telethon] library.

**[irgramd primary repository] is in [darcs] version control system, [github
repository] is synched as secondary**

**irgramd is a fork from [pbui/irtelegramd] to resume the development**

**irgramd is under active development in alpha state, several planned features
are not implemented yet**

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
[github repository]: https://github.com/prsai/irgramd
[pbui/irtelegramd]: https://github.com/pbui/irtelegramd
