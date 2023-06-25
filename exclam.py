# irgramd: IRC-Telegram gateway
# exclam.py: IRC exclamation command handlers
#
# Copyright (c) 2023 E. Bosch <presidev@AT@gmail.com>
#
# Use of this source code is governed by a MIT style license that
# can be found in the LICENSE file included in this project.

from utils import command, HELP

class exclam(command):
    def __init__(self, telegram):
        self.commands = \
        { # Command         Handler                       Arguments  Min Max Maxsplit
            '!re':        (self.handle_command_re,                    2,  2,  2),
        }
        self.tg = telegram
        self.irc = telegram.irc
        self.tmp_ircnick = None
        self.tmp_telegram_id = None
        self.tmp_tg_msg = None

    async def command(self, message, telegram_id, user):
        self.tmp_telegram_id = telegram_id
        res = await self.parse_command(message, nick=None)
        if isinstance(res, tuple):
            await self.irc.send_msg(self.irc.service_user, None, res[0], user)
            res = False
        return res, self.tmp_tg_msg

    async def handle_command_re(self, cid=None, msg=None, help=None):
        if not help:
            id = self.tg.mid.id_to_num_offset(self.tmp_telegram_id, cid)
            chk_msg = await self.tg.telegram_client.get_messages(entity=self.tmp_telegram_id, ids=id)
            if chk_msg is not None:
              self.tmp_tg_msg = await self.tg.telegram_client.send_message(self.tmp_telegram_id, msg, reply_to=id)
              reply = True
            else:
              reply = ('Unknown message to reply',)
        else: # HELP.brief or HELP.desc (first line)
            reply = ('   !re         Reply to a message',)
        if help == HELP.desc:  # rest of HELP.desc
            reply += \
            (
              '   !re <compact_id> <message>',
              'Reply with <message> to a message with <compact_id> on current',
              'channel/chat.'
            )
        return reply
