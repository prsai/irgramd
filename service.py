# irgramd: IRC-Telegram gateway
# service.py: IRC service/control command handlers
#
# Copyright (c) 2022,2023 E. Bosch <presidev@AT@gmail.com>
#
# Use of this source code is governed by a MIT style license that
# can be found in the LICENSE file included in this project.

from utils import compact_date
from telethon import utils as tgutils

class service:
    def __init__(self, settings, telegram):
        self.commands = \
        { # Command         Handler                       Arguments  Min Max
            'code':        (self.handle_command_code,                 1,  1),
            'dialog':      (self.handle_command_dialog,               1,  2),
            'help':        (self.handle_command_help,                 0,  1),
        }
        self.ask_code = settings['ask_code']
        self.tg = telegram
        self.tmp_ircnick = None

    async def parse_command(self, line, nick):

        words = line.split()
        command = words.pop(0).lower()
        self.tmp_ircnick = nick
        if command in self.commands.keys():
            handler, min_args, max_args = self.commands[command]
            num_words = len(words)
            if num_words < min_args or num_words > max_args:
                reply = ('Wrong number of arguments',)
            else:
                reply = await handler(*words)
        else:
            reply = ('Unknown command',)

        return reply

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
            reply = ('   code      Enter authorization code',)
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
                    last = compact_date(dialog.date)
                    if id == self.tg.id:
                        name_in_irc = self.tmp_ircnick
                    else:
                        if id in self.tg.tid_to_iid.keys():
                            name_in_irc = self.tg.tid_to_iid[id]
                        else:
                            name_in_irc = '<Unknown>'
                    reply += (' {:<11d} {:<9d} {:<9d} {:5} {:<3} {:<4} {:<6}  {}'.format(
                                id,     unr,   men,   ty,  pin,  arch, last, name_in_irc),
                             )

        else: # HELP.brief or HELP.desc (first line)
            reply = ('   dialog    Manage conversations (dialogs)',)
        if help == HELP.desc:  # rest of HELP.desc
            reply += \
            (
              '   dialog <subcommand> [id]',
              'Manage conversations (dialogs) established in Telegram, the',
              'following subcommands are available:',
              '   archive <id>   Archive the dialog specified by id',
              '   delete <id>    Delete the dialog specified by id',
              '   list           Show all dialogs',
            )
        return reply

    async def handle_command_help(self, help_command=None, help=None):

        start_help = ('*** Telegram Service Help ***',)
        end_help = ('*** End of Help ***',)

        if help == HELP.brief:
            help_text = ('   help      This help',)
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
              'If you need more information about a specific command you can use',
              'help <command>',
            )
            help_text += end_help
        elif help_command in self.commands.keys():
            handler = self.commands[help_command][0]
            help_text = start_help
            help_text += await handler(help=HELP.desc)
            help_text += end_help
        else:
            help_text = ('help: Unknown command',)
        return help_text


class HELP:
    desc = 1
    brief = 2
