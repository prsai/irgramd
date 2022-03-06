# irgramd: IRC-Telegram gateway
# service.py: IRC service/control command handlers
#
# Copyright (c) 2022 E. Bosch <presidev@AT@gmail.com>
#
# Use of this source code is governed by a MIT style license that
# can be found in the LICENSE file included in this project.

class service:
    def __init__(self):
        self.commands = \
        { # Command         Handler                       Arguments  Min Max
            'help':        (self.handle_command_help,                 0,  1),
        }

    def parse_command(self, line):

        words = line.split()
        command = words.pop(0).lower()
        if command in self.commands.keys():
            handler, min_args, max_args = self.commands[command]
            num_words = len(words)
            if num_words < min_args or num_words > max_args:
                reply = ('Wrong number of arguments',)
            else:
                reply = handler(*words)
        else:
            reply = ('Unknown command',)

        return reply

    def handle_command_help(self, help_command=None, help=None):

        start_help = ('*** Telegram Service Help ***',)
        end_help = ('*** End of Help ***',)

        if not help_command or help_command == 'help':
            help_text = start_help
            help_text += \
            (
              'This service contains specific Telegram commands that irgramd',
              'cannot map to IRC commands. The following commands are available:',
            )
            for command in self.commands.values():
                handler = command[0]
                if handler == self.handle_command_help: break
                help_text += handler(help=HELP.brief)
            help_text += \
            (
              'If you need more information about a specific command you can use',
              'help <command>',
            )
            help_text += end_help
        elif help_command in self.commands.keys():
            handler = self.commands[help_command][0]
            help_text = start_help
            help_text += handler(help=HELP.desc)
            help_text += end_help
        else:
            help_text = ('help: Unknown command',)
        return help_text


class HELP:
    desc = 1
    brief = 2
