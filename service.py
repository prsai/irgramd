# irgramd: IRC-Telegram gateway
# service.py: IRC service/control command handlers
#
# Copyright (c) 2022-2024 E. Bosch <presidev@AT@gmail.com>
#
# Use of this source code is governed by a MIT style license that
# can be found in the LICENSE file included in this project.

from utils import compact_date, command, HELP
from telethon import utils as tgutils
from telethon.errors.rpcerrorlist import SessionPasswordNeededError

class service(command):
    def __init__(self, settings, telegram):
        self.commands = \
        { # Command         Handler                       Arguments  Min Max Maxsplit
            'code':        (self.handle_command_code,                 1,  2, -1),
            'dialog':      (self.handle_command_dialog,               1,  2, -1),
            'help':        (self.handle_command_help,                 0,  1, -1),
            'mark_read':   (self.handle_command_mark_read,            1,  1, -1),
        }
        self.ask_code = settings['ask_code']
        self.init_help = settings['initial_help']
        self.timezone = settings['timezone']
        self.tg = telegram
        self.irc = telegram.irc
        self.tmp_ircnick = None

    def initial_help(self):
        return (
                  'Welcome to irgramd service',
                  'use /msg {} help'.format(self.irc.service_user.irc_nick),
                  'or equivalent in your IRC client',
                  'to get help',
               )

    def auth_help(self):
        sep = '----' if self.init_help else ''
        return (
                  sep,
                  'Your Telegram account is not authorized yet,',
                  'you must supply the code that Telegram sent to your phone',
                  'or another client that is currently connected',
                  'use /msg or equivalent in your IRC client',
                  'e.g. /msg {} code 12345'.format(self.irc.service_user.irc_nick),
                  'If 2nd authentication factor (2FA) password is enabled in',
                  'your account, you must provide it as well',
                  'e.g. /msg {} code 12345 password'.format(self.irc.service_user.irc_nick),
               )

    async def handle_command_code(self, code=None, passw=None, help=None):
        if not help:
            if self.ask_code:
                reply = ('Code will be asked on console',)
            elif code.isdigit():
                valid_auth = True
                try:
                    await self.tg.telegram_client.sign_in(code=code)
                except SessionPasswordNeededError:
                    try:
                        await self.tg.telegram_client.sign_in(password=passw)
                    except:
                        reply = ('Invalid 2FA password',)
                        valid_auth = False
                except:
                    reply = ('Invalid code',)
                    valid_auth = False
                if valid_auth:
                    reply = ('Valid authentication', 'Telegram account authorized')
                    await self.tg.continue_auth()
            else: # not isdigit
                reply = ('Code must be numeric',)

        else: # HELP.brief or HELP.desc (first line)
            reply = ('   code        Enter authorization code and 2FA password',)
        if help == HELP.desc:  # rest of HELP.desc
            reply += \
            (
              '   code <code> [<password>]',
              'Enter authorization code sent by Telegram to the phone or to',
              'another client connected. If 2nd factor authentication (2FA) password',
              'is enabled in your account, must be provided too.',
              'This authentication usually is only needed the first time',
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
                    last = compact_date(dialog.date, self.timezone)
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
