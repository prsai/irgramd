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
        {
            # Command       Handler                       Arguments  Min Max
            'help':        (self.handle_command_help,                 0,  0),
        }

    def parse_command(self, line):

        words = line.split()
        command = words.pop(0).lower()
        if command in self.commands.keys():
            handler, min_args, max_args = self.commands[command]
            num_words = len(words)
            if num_words < min_args or num_words > max_args:
                reply = 'Wrong number of arguments'
            else:
                reply = handler(*words)
        else:
            reply = 'Unknown command'

        return reply

    def handle_command_help(self):
        return 'help'
