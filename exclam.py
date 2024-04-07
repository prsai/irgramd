# irgramd: IRC-Telegram gateway
# exclam.py: IRC exclamation command handlers
#
# Copyright (c) 2023, 2024 E. Bosch <presidev@AT@gmail.com>
#
# Use of this source code is governed by a MIT style license that
# can be found in the LICENSE file included in this project.

from telethon.errors.rpcerrorlist import MessageNotModifiedError, MessageAuthorRequiredError

from utils import command, HELP

class exclam(command):
    def __init__(self, telegram):
        self.commands = \
        { # Command         Handler                       Arguments  Min Max Maxsplit
            '!re':        (self.handle_command_re,                    2,  2,  2),
            '!ed':        (self.handle_command_ed,                    2,  2,  2),
            '!del':       (self.handle_command_del,                   1,  1, -1),
            '!fwd':       (self.handle_command_fwd,                   2,  2, -1),
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

    async def check_msg(self, cid):
        id = self.tg.mid.id_to_num_offset(self.tmp_telegram_id, cid)
        if id is None:
            chk_msg = None
        else:
            chk_msg = await self.tg.telegram_client.get_messages(entity=self.tmp_telegram_id, ids=id)
        return id, chk_msg

    async def handle_command_re(self, cid=None, msg=None, help=None):
        if not help:
            id, chk_msg = await self.check_msg(cid)
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

    async def handle_command_ed(self, cid=None, new_msg=None, help=None):
        if not help:
            id, ed_msg = await self.check_msg(cid)
            if ed_msg is not None:
                try:
                    self.tmp_tg_msg = await self.tg.telegram_client.edit_message(ed_msg, new_msg)
                except MessageNotModifiedError:
                    self.tmp_tg_msg = ed_msg
                    reply = True
                except MessageAuthorRequiredError:
                    reply = ('Not the author of the message to edit',)
                else:
                    reply = True
            else:
                reply = ('Unknown message to edit',)
        else: # HELP.brief or HELP.desc (first line)
            reply = ('   !ed         Edit a message',)
        if help == HELP.desc:  # rest of HELP.desc
            reply += \
            (
              '   !ed <compact_id> <new_message>',
              'Edit a message with <compact_id> on current channel/chat,',
              '<new_message> replaces the current message.'
            )
        return reply

    async def handle_command_del(self, cid=None, help=None):
        if not help:
            id, del_msg = await self.check_msg(cid)
            if del_msg is not None:
                deleted = await self.tg.telegram_client.delete_messages(self.tmp_telegram_id, del_msg)
                if deleted[0].pts_count == 0:
                    reply = ('Not possible to delete',)
                else:
                    self.tmp_tg_msg = None
                    reply = None
            else:
                reply = ('Unknown message to delete',)
        else: # HELP.brief or HELP.desc (first line)
            reply = ('   !del        Delete a message',)
        if help == HELP.desc:  # rest of HELP.desc
            reply += \
            (
              '   !del <compact_id>',
              'Delete a message with <compact_id> on current channel/chat'
            )
        return reply

    async def handle_command_fwd(self, cid=None, chat=None, help=None):
        if not help:
            id, chk_msg = await self.check_msg(cid)
            if chk_msg is not None:
                async def send_fwd(tgt_ent, id):
                    from_ent = await self.tg.telegram_client.get_entity(self.tmp_telegram_id)
                    self.tmp_tg_msg = await self.tg.telegram_client.forward_messages(tgt_ent, id, from_ent)
                    return self.tmp_tg_msg

                tgt = chat.lower()
                if tgt in self.irc.iid_to_tid:
                    tgt_ent = await self.tg.telegram_client.get_entity(self.irc.iid_to_tid[tgt])
                    msg = await send_fwd(tgt_ent, id)
                    # echo fwded message
                    await self.tg.handle_telegram_message(event=None, message=msg)
                    reply = True
                elif tgt in (u.irc_nick.lower() for u in self.irc.users.values() if u.stream):
                    tgt_ent = await self.tg.telegram_client.get_me()
                    await send_fwd(tgt_ent, id)
                    reply = True
                else:
                    reply = ('Unknown chat to forward',)
            else:
                reply = ('Unknown message to forward',)
        else: # HELP.brief or HELP.desc (first line)
            reply = ('   !fwd        Forward a message',)
        if help == HELP.desc:  # rest of HELP.desc
            reply += \
            (
              '   !fwd <compact_id> <chat>',
              'Forward a message with <compact_id> to <chat> channel/chat.'
            )
        return reply
