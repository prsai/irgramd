# irgramd: IRC-Telegram gateway
# service.py: IRC service/control command handlers
#
# Copyright (c) 2022,2023 E. Bosch <presidev@AT@gmail.com>
#
# Use of this source code is governed by a MIT style license that
# can be found in the LICENSE file included in this project.

from utils import compact_date, command, HELP
from telethon import utils as tgutils

class service(command):
    def __init__(self, settings, telegram):
        self.commands = \
        { # Command         Handler                       Arguments  Min Max Maxsplit
            'code':        (self.handle_command_code,                 1,  1, -1),
            'dialog':      (self.handle_command_dialog,               1,  2, -1),
            'get':         (self.handle_command_get,                  2,  2, -1),
            'help':        (self.handle_command_help,                 0,  1, -1),
            'history':     (self.handle_command_history,              1,  3, -1),
            'mark_read':   (self.handle_command_mark_read,            1,  1, -1),
        }
        self.ask_code = settings['ask_code']
        self.tg = telegram
        self.irc = telegram.irc
        self.tmp_ircnick = None

    async def handle_command_code(self, code=None, help=None):
        if not help:
            if self.ask_code:
                reply = ('Code will be asked on console',)
            elif code.isdigit():
                try:
                    await self.tg.telegram_client.sign_in(code=code)
                except:
                    reply = ('Invalid code',)
                else:
                    reply = ('Valid code', 'Telegram account authorized')
                    await self.tg.continue_auth()
            else: # not isdigit
                reply = ('Code must be numeric',)

        else: # HELP.brief or HELP.desc (first line)
            reply = ('   code        Enter authorization code',)
        if help == HELP.desc:  # rest of HELP.desc
            reply += \
            (
              '   code <code>',
              'Enter authorization code sent by Telegram to the phone or to',
              'another client connected.',
              'This authorization code usually is only needed the first time',
              'that irgramd connects to Telegram with a given account.',
            )
        return reply

    async def handle_command_dialog(self, command=None, id=None, help=None):
        if not help:
            if command == 'archive':
                pass
            elif command == 'delete':
                pass
            elif command == 'list':
                reply = \
                (
                  'Dialogs:',
                  ' {:<11} {:<9} {:<9} {:5} {:<3} {:<4} {:<6}  {}'.format(
                      'Id', 'Unread', 'Mentions', 'Type', 'Pin', 'Arch', 'Last', 'Name'),
                )
                async for dialog in self.tg.telegram_client.iter_dialogs():
                    id, type = tgutils.resolve_id(dialog.id)
                    unr = dialog.unread_count
                    men = dialog.unread_mentions_count
                    ty = self.tg.get_entity_type(dialog.entity, format='short')
                    pin = 'Yes' if dialog.pinned else 'No'
                    arch = 'Yes' if dialog.archived else 'No'
                    last = compact_date(dialog.date, self.tg.timezone)
                    if id == self.tg.id:
                        name_in_irc = self.tmp_ircnick
                    else:
                        name_in_irc = self.tg.get_irc_name_from_telegram_id(id)

                    reply += (' {:<11d} {:<9d} {:<9d} {:5} {:<3} {:<4} {:<6}  {}'.format(
                                id,     unr,   men,   ty,  pin,  arch, last, name_in_irc),
                             )

        else: # HELP.brief or HELP.desc (first line)
            reply = ('   dialog      Manage conversations (dialogs)',)
        if help == HELP.desc:  # rest of HELP.desc
            reply += \
            (
              '   dialog <subcommand> [id]',
              'Manage conversations (dialogs) established in Telegram, the',
              'following subcommands are available:',
#              '   archive <id>   Archive the dialog specified by id',
#              '   delete <id>    Delete the dialog specified by id',
              '   list           Show all dialogs',
            )
        return reply

    async def handle_command_get(self, peer=None, mid=None, help=None):
        if not help:
            msg = None
            peer_id, reply = self.get_peer_id(peer.lower())
            if reply: return reply
            else: reply = ()

            # If the ID starts with '=' is absolute ID, not compact ID
            # character '=' is not used by compact IDs
            if mid[0] == '=':
                id = int(mid[1:])
            else:
                id = self.tg.mid.id_to_num_offset(peer_id, mid)
            if id is not None:
                msg = await self.tg.telegram_client.get_messages(entity=peer_id, ids=id)
            if msg is not None:
                await self.tg.handle_telegram_message(event=None, message=msg, history=True)
            else:
                reply = ('Message not found',)
            return reply

        else: # HELP.brief or HELP.desc (first line)
            reply = ('   get         Get a message by id and peer',)
        if help == HELP.desc:  # rest of HELP.desc
            reply += \
            (
              '   get <peer> <compact_id|=ID>',
              'Get one message from peer with the compact or absolute ID',
            )
        return reply

    async def handle_command_help(self, help_command=None, help=None):

        start_help = ('*** Telegram Service Help ***',)
        end_help = ('*** End of Help ***',)

        if help == HELP.brief:
            help_text = ('   help        This help',)
        elif not help_command or help_command == 'help':
            help_text = start_help
            help_text += \
            (
              'This service contains specific Telegram commands that irgramd',
              'cannot map to IRC commands. The following commands are available:',
            )
            for command in self.commands.values():
                handler = command[0]
                help_text += await handler(help=HELP.brief)
            help_text += \
            (
              'The commands begining with ! (exclamation) must be used directly',
              'in channels or chats. The following ! commands are available:',
            )
            for command in self.irc.exclam.commands.values():
                handler = command[0]
                help_text += await handler(help=HELP.brief)
            help_text += \
            (
              'If you need more information about a specific command you can use',
              'help <command>',
            )
            help_text += end_help
        elif help_command in (all_commands := dict(**self.commands, **self.irc.exclam.commands)).keys():
            handler = all_commands[help_command][0]
            help_text = start_help
            help_text += await handler(help=HELP.desc)
            help_text += end_help
        else:
            help_text = ('help: Unknown command',)
        return help_text

    async def handle_command_history(self, peer=None, limit='10', add_unread=None, help=None):
        if not help:
            async def get_unread(tgt):
                async for dialog in self.tg.telegram_client.iter_dialogs():
                    id, type = tgutils.resolve_id(dialog.id)
                    if id in self.tg.tid_to_iid.keys():
                        name = self.tg.tid_to_iid[id]
                        if tgt == name.lower():
                            count = dialog.unread_count
                            reply = None
                            break
                else:
                    count = None
                    reply = ('Unknown unread',)
                return count, reply

            def conv_int(num_str):
                if num_str.isdigit():
                    n = int(num_str)
                    err = None
                else:
                    n = None
                    err = ('Invalid argument',)
                return n, err

            tgt = peer.lower()
            peer_id, reply = self.get_peer_id(tgt)
            if reply: return reply

            if limit == 'unread':
                add_unread = '0' if add_unread is None else add_unread
                add_unread_int, reply = conv_int(add_unread)
                if reply: return reply

                li, reply = await get_unread(tgt)
                if reply: return reply
                li += add_unread_int
            elif add_unread is not None:
                reply = ('Wrong number of arguments',)
                return reply
            elif limit == 'all':
                li = None
            else:
                li, reply = conv_int(limit)
                if reply: return reply

            his = await self.tg.telegram_client.get_messages(peer_id, limit=li)
            for msg in reversed(his):
                await self.tg.handle_telegram_message(event=None, message=msg, history=True)
            reply = ()
            return reply

        else: # HELP.brief or HELP.desc (first line)
            reply = ('   history     Get messages from history',)
        if help == HELP.desc:  # rest of HELP.desc
            reply += \
            (
              '   history <peer> [<limit>|all|unread [<plusN>]]',
              'Get last <limit> number of messages already sent to <peer>',
              '(channel or user). If not set <limit> is 10.',
              'Instead of <limit>, "unread" is for messages not marked as read,',
              'optionally <plusN> number of previous messages to the first unread.',
              'Instead of <limit>, "all" is for retrieving all available messages',
              'in <peer>.',
            )
        return reply

    async def handle_command_mark_read(self, peer=None, help=None):
        if not help:
            peer_id, reply = self.get_peer_id(peer.lower())
            if reply: return reply

            await self.tg.telegram_client.send_read_acknowledge(peer_id, clear_mentions=True)
            reply = ('',)
        else: # HELP.brief or HELP.desc (first line)
            reply = ('   mark_read   Mark messages as read',)
        if help == HELP.desc:  # rest of HELP.desc
            reply += \
            (
              '   mark_read <peer>',
              'Mark all messages on <peer> (channel or user) as read, this also will',
              'reset the number of mentions to you on <peer>.',
            )
        return reply

    def get_peer_id(self, tgt):
        if tgt in self.irc.users or tgt in self.irc.irc_channels:
            peer_id = self.tg.get_tid(tgt)
            reply = None
        else:
            peer_id = None
            reply = ('Unknown user or channel',)
        return peer_id, reply
