# irgramd: IRC-Telegram gateway
# telegram.py: Interface to Telethon Telegram library
#
# Copyright (c) 2019 Peter Bui <pbui@bx612.space>
# Copyright (c) 2020-2024 E. Bosch <presidev@AT@gmail.com>
#
# Use of this source code is governed by a MIT style license that
# can be found in the LICENSE file included in this project.

import logging
import os
import re
import aioconsole
import asyncio
import collections
import telethon
from telethon import types as tgty, utils as tgutils
from telethon.tl.functions.messages import GetMessagesReactionsRequest

# Local modules

from include import CHAN_MAX_LENGTH, NICK_MAX_LENGTH
from irc import IRCUser
from utils import sanitize_filename, add_filename, is_url_equiv, extract_url, get_human_size, get_human_duration
from utils import get_highlighted, fix_braces, format_timestamp, pretty, current_date
import emoji2emoticon as e

# Test IP table

TEST_IPS = { 1: '149.154.175.10',
             2: '149.154.167.40',
             3: '149.154.175.117',
           }

    # Telegram

class TelegramHandler(object):
    def __init__(self, irc, settings):
        self.logger     = logging.getLogger()
        self.config_dir = settings['config_dir']
        self.cache_dir  = settings['cache_dir']
        self.download   = settings['download_media']
        self.notice_size = settings['download_notice'] * 1048576
        self.media_dir  = settings['media_dir']
        self.media_url  = settings['media_url']
        self.upload_dir = settings['upload_dir']
        self.api_id     = settings['api_id']
        self.api_hash   = settings['api_hash']
        self.phone      = settings['phone']
        self.test       = settings['test']
        self.test_dc    = settings['test_datacenter']
        self.test_ip    = settings['test_host'] if settings['test_host'] else TEST_IPS[self.test_dc]
        self.test_port  = settings['test_port']
        self.ask_code   = settings['ask_code']
        self.quote_len  = settings['quote_length']
        self.hist_fmt   = settings['hist_timestamp_format']
        self.timezone   = settings['timezone']
        self.geo_url    = settings['geo_url']
        if not settings['emoji_ascii']:
            e.emo = {}
        self.media_cn   = 0
        self.irc        = irc
        self.authorized = False
        self.id	= None
        self.tg_username = None
        self.channels_date = {}
        self.mid = mesg_id('0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ!#$%+./_~')
        self.webpending = {}
        self.refwd_me = False
        self.cache = collections.OrderedDict()
        self.volatile_cache = collections.OrderedDict()
        self.prev_id = {}
        self.sorted_len_usernames = []
        self.last_reaction = None
        # Set event to be waited by irc.check_telegram_auth()
        self.auth_checked = asyncio.Event()

    async def initialize_telegram(self):
        # Setup media folder
        self.telegram_media_dir = os.path.expanduser(self.media_dir or os.path.join(self.cache_dir, 'media'))
        if not os.path.exists(self.telegram_media_dir):
            os.makedirs(self.telegram_media_dir)

        # Setup upload folder
        self.telegram_upload_dir = os.path.expanduser(self.upload_dir or os.path.join(self.cache_dir, 'upload'))
        if not os.path.exists(self.telegram_upload_dir):
            os.makedirs(self.telegram_upload_dir)

        # Setup session folder
        self.telegram_session_dir = os.path.join(self.config_dir, 'session')
        if not os.path.exists(self.telegram_session_dir):
            os.makedirs(self.telegram_session_dir)

        # Construct Telegram client
        if self.test:
            self.telegram_client = telethon.TelegramClient(None, self.api_id, self.api_hash)
            self.telegram_client.session.set_dc(self.test_dc, self.test_ip, self.test_port)
        else:
            telegram_session = os.path.join(self.telegram_session_dir, 'telegram')
            self.telegram_client = telethon.TelegramClient(telegram_session, self.api_id, self.api_hash)

        # Initialize Telegram ID to IRC nick mapping
        self.tid_to_iid = {}

        # Register Telegram callbacks
        callbacks = (
            (self.handle_telegram_message    , telethon.events.NewMessage),
            (self.handle_raw                 , telethon.events.Raw),
            (self.handle_telegram_chat_action, telethon.events.ChatAction),
            (self.handle_telegram_deleted    , telethon.events.MessageDeleted),
            (self.handle_telegram_edited     , telethon.events.MessageEdited),
        )
        for handler, event in callbacks:
            self.telegram_client.add_event_handler(handler, event)

        # Start Telegram client
        if self.test:
            await self.telegram_client.start(self.phone, code_callback=lambda: str(self.test_dc) * 5)
        else:
            await self.telegram_client.connect()

        while not await self.telegram_client.is_user_authorized():
            self.logger.info('Telegram account not authorized')
            await self.telegram_client.send_code_request(self.phone)
            self.auth_checked.set()
            if not self.ask_code:
                return
            self.logger.info('You must provide the Login code that Telegram will '
                             'sent you via SMS or another connected client')
            code = await aioconsole.ainput('Login code: ')
            try:
                await self.telegram_client.sign_in(code=code)
            except:
                pass

        await self.continue_auth()

    async def continue_auth(self):
        self.logger.info('Telegram account authorized')
        self.authorized = True
        self.auth_checked.set()
        await self.init_mapping()

    async def init_mapping(self):
        # Update IRC <-> Telegram mapping
        tg_user = await self.telegram_client.get_me()
        self.id = tg_user.id
        self.tg_username = self.get_telegram_nick(tg_user)
        self.add_sorted_len_usernames(self.tg_username)
        self.set_ircuser_from_telegram(tg_user)
        async for dialog in self.telegram_client.iter_dialogs():
            chat = dialog.entity
            if isinstance(chat, tgty.User):
                self.set_ircuser_from_telegram(chat)
            else:
                await self.set_irc_channel_from_telegram(chat)

    def set_ircuser_from_telegram(self, user):
        if user.id not in self.tid_to_iid:
            tg_nick = self.get_telegram_nick(user)
            tg_ni = tg_nick.lower()
            if not user.is_self:
                irc_user = IRCUser(None, ('Telegram',''), tg_nick, user.id, self.get_telegram_display_name(user))
                self.irc.users[tg_ni] = irc_user
                self.add_sorted_len_usernames(tg_ni)
            self.tid_to_iid[user.id] = tg_nick
            self.irc.iid_to_tid[tg_ni] = user.id
        else:
            tg_nick = self.tid_to_iid[user.id]
        return tg_nick

    async def set_irc_channel_from_telegram(self, chat):
        channel = self.get_telegram_channel(chat)
        self.tid_to_iid[chat.id] = channel
        chan = channel.lower()
        self.irc.iid_to_tid[chan] = chat.id
        self.irc.irc_channels[chan] = set()
        # Add users from the channel
        async for user in self.telegram_client.iter_participants(chat.id):
            user_nick = self.set_ircuser_from_telegram(user)
            if not user.is_self:
                self.irc.irc_channels[chan].add(user_nick)
            # Add admin users as ops in irc
            if isinstance(user.participant, tgty.ChatParticipantAdmin):
                self.irc.irc_channels_ops[chan].add(user_nick)
            # Add creator users as founders in irc
            elif isinstance(user.participant, tgty.ChatParticipantCreator):
                self.irc.irc_channels_founder[chan].add(user_nick)

    def get_telegram_nick(self, user):
        nick = (user.username
                or self.get_telegram_display_name(user)
                or str(user.id))
        nick = nick[:NICK_MAX_LENGTH]
        while nick in self.irc.iid_to_tid:
            nick += '_'
        return nick

    def get_telegram_display_name(self, user):
        name = telethon.utils.get_display_name(user)
        name = name.replace(' ', '_')
        return name

    async def get_telegram_display_name_me(self):
        tg_user = await self.telegram_client.get_me()
        return self.get_telegram_display_name(tg_user)

    def get_telegram_channel(self, chat):
        chan = '#' + chat.title.replace(' ', '-').replace(',', '-')
        while chan.lower() in self.irc.iid_to_tid:
            chan += '_'
        return chan

    def get_irc_user_from_telegram(self, tid):
        nick = self.tid_to_iid[tid]
        if nick == self.tg_username: return None
        return self.irc.users[nick.lower()]

    def get_irc_name_from_telegram_id(self, tid):
        if tid in self.tid_to_iid.keys():
            name_in_irc = self.tid_to_iid[tid]
        else:
            name_in_irc = '<Unknown>'
        return name_in_irc

    async def get_irc_name_from_telegram_forward(self, fwd, saved):
        from_id = fwd.saved_from_peer if saved else fwd.from_id
        if from_id is None:
            # telegram user has privacy options to show only the name
            # or was a broadcast from a channel (no user)
            name = fwd.from_name
        else:
            peer_id, type = self.get_peer_id_and_type(from_id)
            if type == 'user':
                try:
                    user = self.get_irc_user_from_telegram(peer_id)
                except:
                    name = str(peer_id)
                else:
                    if user is None:
                        name = '{}'
                        self.refwd_me = True
                    else:
                        name = user.irc_nick
            else:
                try:
                    name = await self.get_irc_channel_from_telegram_id(peer_id)
                except:
                    name = ''
        return name

    async def get_irc_nick_from_telegram_id(self, tid, entity=None):
        if tid not in self.tid_to_iid:
            user = entity or await self.telegram_client.get_entity(tid)
            nick = self.get_telegram_nick(user)
            self.tid_to_iid[tid]  = nick
            self.irc.iid_to_tid[nick] = tid

        return self.tid_to_iid[tid]

    async def get_irc_channel_from_telegram_id(self, tid, entity=None):
        rtid, type = tgutils.resolve_id(tid)
        if rtid not in self.tid_to_iid:
            chat    = entity or await self.telegram_client.get_entity(tid)
            channel = self.get_telegram_channel(chat)
            self.tid_to_iid[rtid]     = channel
            self.irc.iid_to_tid[channel] = rtid

        return self.tid_to_iid[rtid]

    async def get_telegram_channel_participants(self, tid):
        channel = self.tid_to_iid[tid]
        nicks   = []
        async for user in self.telegram_client.iter_participants(tid):
            user_nick = await self.get_irc_nick_from_telegram_id(user.id, user)

            nicks.append(user_nick)
            self.irc.irc_channels[channel].add(user_nick)

        return nicks

    async def get_telegram_idle(self, irc_nick, tid=None):
        if self.irc.users[irc_nick].is_service:
            return None
        tid = self.get_tid(irc_nick, tid)
        user = await self.telegram_client.get_entity(tid)
        if isinstance(user.status,tgty.UserStatusRecently) or \
           isinstance(user.status,tgty.UserStatusOnline):
            idle = 0
        elif isinstance(user.status,tgty.UserStatusOffline):
            last = user.status.was_online
            current = current_date()
            idle = int((current - last).total_seconds())
        elif isinstance(user.status,tgty.UserStatusLastWeek):
            idle = 604800
        elif isinstance(user.status,tgty.UserStatusLastMonth):
            idle = 2678400
        else:
            idle = None
        return idle

    async def get_channel_topic(self, channel, entity_cache):
        tid = self.get_tid(channel)
        # entity_cache should be a list to be a persistent and by reference value
        if entity_cache[0]:
            entity = entity_cache[0]
        else:
            entity = await self.telegram_client.get_entity(tid)
            entity_cache[0] = entity
        entity_type = self.get_entity_type(entity, format='long')
        return 'Telegram ' + entity_type + ' ' + str(tid) + ': ' + entity.title

    async def get_channel_creation(self, channel, entity_cache):
        tid = self.get_tid(channel)
        if tid in self.channels_date.keys():
            timestamp = self.channels_date[tid]
        else:
            # entity_cache should be a list to be a persistent and by reference value
            if entity_cache[0]:
                entity = entity_cache[0]
            else:
                entity = await self.telegram_client.get_entity(tid)
                entity_cache[0] = entity
            timestamp = entity.date.timestamp()
            self.channels_date[tid] = timestamp
        return int(timestamp)

    def get_tid(self, irc_item, tid=None):
        it = irc_item.lower()
        if tid:
            pass
        elif it in self.irc.iid_to_tid:
            tid = self.irc.iid_to_tid[it]
        else:
            tid = self.id
        return tid

    def get_entity_type(self, entity, format):
        if isinstance(entity, tgty.User):
            short = long = 'User'
        elif isinstance(entity, tgty.Chat):
            short = 'Chat'
            long = 'Chat/Basic Group'
        elif isinstance(entity, tgty.Channel):
            if entity.broadcast:
                short = 'Broad'
                long = 'Broadcast Channel'
            elif entity.megagroup:
                short = 'Mega'
                long = 'Super/Megagroup Channel'
            elif entity.gigagroup:
                short = 'Giga'
                long = 'Broadcast Gigagroup Channel'

        return short if format == 'short' else long

    def get_peer_id_and_type(self, peer):
        if isinstance(peer, tgty.PeerChannel):
            id = peer.channel_id
            type = 'chan'
        elif isinstance(peer, tgty.PeerChat):
            id = peer.chat_id
            type = 'chan'
        elif isinstance(peer, tgty.PeerUser):
            id = peer.user_id
            type = 'user'
        else:
            id = peer
            type = ''
        return id, type

    async def is_bot(self, irc_nick, tid=None):
        user = self.irc.users[irc_nick]
        if user.stream or user.is_service:
            bot = False
        else:
            bot = user.bot
        if bot == None:
            tid = self.get_tid(irc_nick, tid)
            tg_user = await self.telegram_client.get_entity(tid)
            bot = tg_user.bot
            user.bot = bot
        return bot

    async def edition_case(self, msg):
        def msg_edited(m):
            return m.id in self.cache and \
                   ( m.message != self.cache[m.id]['text']
                     or m.media != self.cache[m.id]['media']
                   )
        async def get_reactions(m):
            react = await self.telegram_client(GetMessagesReactionsRequest(m.peer_id, id=[m.id]))
            updates = react.updates
            r = next((x for x in updates if type(x) is tgty.UpdateMessageReactions), None)
            return r.reactions.recent_reactions if r else None

        react = None
        if msg.reactions is None:
            case = 'edition'
        elif (reactions := await get_reactions(msg)) is None:
            if msg_edited(msg):
                case = 'edition'
            else:
                case = 'react-del'
        elif react := max(reactions, key=lambda y: y.date):
            case = 'react-add'
        else:
            if msg_edited(msg):
                case = 'edition'
            else:
                case = 'react-del'
            react = None
        return case, react

    def to_cache(self, id, mid, message, proc_message, user, chan, media):
        self.limit_cache(self.cache)
        self.cache[id] = {
                           'mid': mid,
                           'text': message,
                           'rendered_text': proc_message,
                           'user': user,
                           'channel': chan,
                           'media': media,
                         }

    def to_volatile_cache(self, prev_id, id, ev, user, chan, date):
        if chan in prev_id:
            prid = prev_id[chan] if chan else prev_id[user]
            self.limit_cache(self.volatile_cache)
            elem = {
                     'id': id,
                     'rendered_event': ev,
                     'user': user,
                     'channel': chan,
                     'date': date,
                   }
            if prid not in self.volatile_cache:
                self.volatile_cache[prid] = [elem]
            else:
                self.volatile_cache[prid].append(elem)

    def limit_cache(self, cache):
        if len(cache) >= 10000:
            cache.popitem(last=False)

    def replace_mentions(self, text, me_nick='', received=True):
        # For received replace @mention to ~mention~
        # For sent replace mention: to @mention
        rargs = {}
        def repl_mentioned(text, me_nick, received, mark, repl_pref, repl_suff):
            new_text = text

            for user in self.sorted_len_usernames:
                if user == self.tg_username:
                    if me_nick:
                        username = me_nick
                    else:
                        continue
                else:
                    username = self.irc.users[user].irc_nick

                if received:
                    mention = mark + user
                    mention_case = mark + username
                else: # sent
                    mention = user + mark
                    mention_case = username + mark
                replcmnt = repl_pref + username + repl_suff

                # Start of the text
                for ment in (mention, mention_case):
                    if new_text.startswith(ment):
                        new_text = new_text.replace(ment, replcmnt, 1)

                # Next words (with space as separator)
                mention = ' ' + mention
                mention_case = ' ' + mention_case
                replcmnt = ' ' + replcmnt
                new_text = new_text.replace(mention, replcmnt).replace(mention_case, replcmnt)

            return new_text

        if received:
            mark = '@'
            rargs['repl_pref'] = '~'
            rargs['repl_suff'] = '~'
        else: # sent
            mark = ':'
            rargs['repl_pref'] = '@'
            rargs['repl_suff'] = ''

        if text.find(mark) != -1:
            text_replaced = repl_mentioned(text, me_nick, received, mark, **rargs)
        else:
            text_replaced = text
        return text_replaced

    def filters(self, text):
        filtered = e.replace_mult(text, e.emo)
        filtered = self.replace_mentions(filtered)
        return filtered

    def add_sorted_len_usernames(self, username):
        self.sorted_len_usernames.append(username)
        self.sorted_len_usernames.sort(key=lambda k: len(k), reverse=True)

    def format_reaction(self, msg, message_rendered, edition_case, reaction):
        react_quote_len = self.quote_len * 2
        if len(message_rendered) > react_quote_len:
            text_old = '{}...'.format(message_rendered[:react_quote_len])
            text_old = fix_braces(text_old)
        else:
            text_old = message_rendered

        if edition_case == 'react-add':
            user = self.get_irc_user_from_telegram(reaction.peer_id.user_id)
            emoji = reaction.reaction.emoticon
            react_action = '+'
            react_icon = e.emo[emoji] if emoji in e.emo else emoji
        elif edition_case == 'react-del':
            user = self.get_irc_user_from_telegram(msg.sender_id)
            react_action = '-'
            react_icon = ''
        return text_old, '{}{}'.format(react_action, react_icon), user

    async def handle_telegram_edited(self, event):
        self.logger.debug('Handling Telegram Message Edited: %s', pretty(event))

        id = event.message.id
        mid = self.mid.num_to_id_offset(event.message.peer_id, id)
        fmid = '[{}]'.format(mid)
        message = self.filters(event.message.message)
        message_rendered = await self.render_text(event.message, mid, upd_to_webpend=None)

        edition_case, reaction = await self.edition_case(event.message)
        if edition_case == 'edition':
            action = 'Edited'
            user = self.get_irc_user_from_telegram(event.sender_id)
            if id in self.cache:
                t = self.filters(self.cache[id]['text'])
                rt = self.cache[id]['rendered_text']

                ht, is_ht = get_highlighted(t, message)
            else:
                rt = fmid
                is_ht = False

            if is_ht:
                edition_react = ht
                text_old = fmid
            else:
                edition_react = message
                text_old = rt
                if user is None:
                    self.refwd_me = True

        # Reactions
        else:
            if reaction:
                if self.last_reaction == reaction.date:
                    return
                self.last_reaction = reaction.date
            action = 'React'
            text_old, edition_react, user = self.format_reaction(event.message, message_rendered, edition_case, reaction)

        text = '|{} {}| {}'.format(action, text_old, edition_react)

        chan = await self.relay_telegram_message(event, user, text)

        self.to_cache(id, mid, message, message_rendered, user, chan, event.message.media)
        self.to_volatile_cache(self.prev_id, id, text, user, chan, current_date())

    async def handle_next_reaction(self, event):
        self.logger.debug('Handling Telegram Next Reaction (2nd, 3rd, ...): %s', pretty(event))

        reactions = event.reactions.recent_reactions
        react = max(reactions, key=lambda y: y.date)
        
        if self.last_reaction != react.date:
            self.last_reaction = react.date
            id = event.msg_id
            msg = await self.telegram_client.get_messages(entity=event.peer, ids=id)
            mid = self.mid.num_to_id_offset(msg.peer_id, id)
            message = self.filters(msg.message)
            message_rendered = await self.render_text(msg, mid, upd_to_webpend=None)

            text_old, edition_react, user = self.format_reaction(msg, message_rendered, edition_case='react-add', reaction=react)

            text = '|React {}| {}'.format(text_old, edition_react)

            chan = await self.relay_telegram_message(msg, user, text)

            self.to_cache(id, mid, message, message_rendered, user, chan, msg.media)
            self.to_volatile_cache(self.prev_id, id, text, user, chan, current_date())

    async def handle_telegram_deleted(self, event):
        self.logger.debug('Handling Telegram Message Deleted: %s', pretty(event))

        for deleted_id in event.original_update.messages:
            if deleted_id in self.cache:
                recovered_text = self.cache[deleted_id]['rendered_text']
                text = '|Deleted| {}'.format(recovered_text)
                user = self.cache[deleted_id]['user']
                chan = self.cache[deleted_id]['channel']
                await self.relay_telegram_message(message=None, user=user, text=text, channel=chan)
                self.to_volatile_cache(self.prev_id, deleted_id, text, user, chan, current_date())
            else:
                text = 'Message id {} deleted not in cache'.format(deleted_id)
                await self.relay_telegram_private_message(self.irc.service_user, text)

    async def handle_raw(self, update):
        self.logger.debug('Handling Telegram Raw Event: %s', pretty(update))

        if isinstance(update, tgty.UpdateWebPage) and isinstance(update.webpage, tgty.WebPage):
            message = self.webpending.pop(update.webpage.id, None)
            if message:
                await self.handle_telegram_message(event=None, message=message, upd_to_webpend=update.webpage)

        elif isinstance(update, tgty.UpdateMessageReactions):
            await self.handle_next_reaction(update)

    async def handle_telegram_message(self, event, message=None, upd_to_webpend=None, history=False):
        self.logger.debug('Handling Telegram Message: %s', pretty(event or message))

        msg = event.message if event else message

        user = self.get_irc_user_from_telegram(msg.sender_id)
        mid = self.mid.num_to_id_offset(msg.peer_id, msg.id)
        text = await self.render_text(msg, mid, upd_to_webpend, user)
        text_send = self.set_history_timestamp(text, history, msg.date, msg.action)
        chan = await self.relay_telegram_message(msg, user, text_send)
        await self.history_search_volatile(history, msg.id)

        self.to_cache(msg.id, mid, msg.message, text, user, chan, msg.media)
        peer = chan if chan else user
        self.prev_id[peer] = msg.id

        self.refwd_me = False

    async def render_text(self, message, mid, upd_to_webpend, user=None):
        if upd_to_webpend:
            text = await self.handle_webpage(upd_to_webpend, message, mid)
        elif message.media:
            text = await self.handle_telegram_media(message, user, mid)
        else:
            text = message.message

        if message.action:
            final_text = await self.handle_telegram_action(message, mid)
            return final_text
        elif message.is_reply:
            refwd_text = await self.handle_telegram_reply(message)
        elif message.forward:
            refwd_text = await self.handle_telegram_forward(message)
        else:
            refwd_text = ''

        target_mine = self.handle_target_mine(message.peer_id, user)

        final_text = '[{}] {}{}{}'.format(mid, target_mine, refwd_text, text)
        final_text = self.filters(final_text)
        return final_text

    def set_history_timestamp(self, text, history, date, action):
        if history and self.hist_fmt:
            timestamp = format_timestamp(self.hist_fmt, self.timezone, date)
            if action:
                res = '{} {}'.format(text, timestamp)
            else:
                res = '{} {}'.format(timestamp, text)
        else:
            res = text
        return res

    async def history_search_volatile(self, history, id):
        if history:
            if id in self.volatile_cache:
                for item in self.volatile_cache[id]:
                    user = item['user']
                    text = item['rendered_event']
                    chan = item['channel']
                    date = item['date']
                    text_send = self.set_history_timestamp(text, history=True, date=date, action=False)
                    await self.relay_telegram_message(None, user, text_send, chan)

    async def relay_telegram_message(self, message, user, text, channel=None):
        private = (message and message.is_private) or (not message and not channel)
        action = (message and message.action)
        if private:
            await self.relay_telegram_private_message(user, text, action)
            chan = None
        else:
            chan = await self.relay_telegram_channel_message(message, user, text, channel, action)
        return chan

    async def relay_telegram_private_message(self, user, message, action=None):
        self.logger.debug('Relaying Telegram Private Message: %s, %s', user, message)

        if action:
            await self.irc.send_action(user, None, message)
        else:
            await self.irc.send_msg(user, None, message)

    async def relay_telegram_channel_message(self, message, user, text, channel, action):
        if message:
            entity = await message.get_chat()
            chan = await self.get_irc_channel_from_telegram_id(message.chat_id, entity)
        else:
            chan = channel

        self.logger.debug('Relaying Telegram Channel Message: %s, %s', chan, text)

        if action:
            await self.irc.send_action(user, chan, text)
        else:
            await self.irc.send_msg(user, chan, text)

        return chan

    async def handle_telegram_chat_action(self, event):
        self.logger.debug('Handling Telegram Chat Action: %s', pretty(event))

        try:
            tid = event.action_message.to_id.channel_id
        except AttributeError:
            tid = event.action_message.to_id.chat_id
        finally:
            irc_channel = await self.get_irc_channel_from_telegram_id(tid)
            await self.get_telegram_channel_participants(tid)

        try:                                        # Join Chats
            irc_nick = await self.get_irc_nick_from_telegram_id(event.action_message.action.users[0])
        except (IndexError, AttributeError):
            try:                                    # Kick
                irc_nick = await self.get_irc_nick_from_telegram_id(event.action_message.action.user_id)
            except (IndexError, AttributeError):    # Join Channels
                irc_nick = await self.get_irc_nick_from_telegram_id(event.action_message.sender_id)

        if event.user_added or event.user_joined:
            await self.irc.join_irc_channel(irc_nick, irc_channel, full_join=False)
        elif event.user_kicked or event.user_left:
            await self.irc.part_irc_channel(irc_nick, irc_channel)

    async def join_all_telegram_channels(self):
        async for dialog in self.telegram_client.iter_dialogs():
            chat = dialog.entity
            if not isinstance(chat, tgty.User):
                channel = self.get_telegram_channel(chat)
                self.tid_to_iid[chat.id] = channel
                self.irc.iid_to_tid[channel] = chat.id
                await self.irc.join_irc_channel(self.irc.irc_nick, channel, full_join=True)

    async def handle_telegram_action(self, message, mid):
        if isinstance(message.action, tgty.MessageActionPinMessage):
            replied = await message.get_reply_message()
            cid = self.mid.num_to_id_offset(replied.peer_id, replied.id)
            action_text = 'has pinned message [{}]'.format(cid)
        elif isinstance(message.action, tgty.MessageActionChatEditPhoto):
            _, media_type = self.scan_photo_attributes(message.action.photo)
            photo_url = await self.download_telegram_media(message, mid)
            action_text = 'has changed chat [{}] {}'.format(media_type, photo_url)
        else:
            action_text = ''
        return action_text

    async def handle_telegram_reply(self, message):
        space = ' '
        trunc = ''
        replied = await message.get_reply_message()
        if replied:
            replied_msg = replied.message
            cid = self.mid.num_to_id_offset(replied.peer_id, replied.id)
            replied_user = self.get_irc_user_from_telegram(replied.sender_id)
        else:
            replied_id = message.reply_to.reply_to_msg_id
            cid = self.mid.num_to_id_offset(message.peer_id, replied_id)
            if replied_id in self.cache:
                text = self.cache[replied_id]['text']
                replied_user = self.cache[replied_id]['user']
                sp = ' '
            else:
                text = ''
                replied_user = ''
                sp = ''
            replied_msg = '|Deleted|{}{}'.format(sp, text)
        if not replied_msg:
            replied_msg = ''
            space = ''
        elif len(replied_msg) > self.quote_len:
            replied_msg = replied_msg[:self.quote_len]
            trunc = '...'
        if replied_user is None:
            replied_nick = '{}'
            self.refwd_me = True
        elif replied_user == '':
            replied_nick = ''
        else:
            replied_nick = replied_user.irc_nick

        return '|Re {}: [{}]{}{}{}| '.format(replied_nick, cid, space, replied_msg, trunc)

    async def handle_telegram_forward(self, message):
        space = space2 = ' '
        if not (forwarded_peer_name := await self.get_irc_name_from_telegram_forward(message.fwd_from, saved=False)):
            space = ''
        saved_peer_name = await self.get_irc_name_from_telegram_forward(message.fwd_from, saved=True)
        if saved_peer_name and saved_peer_name != forwarded_peer_name:
            secondary_name = saved_peer_name
        else:
            # if it's from me I want to know who was the destination of a message (user)
            if self.refwd_me and (saved_from_peer := message.fwd_from.saved_from_peer) is not None:
               secondary_name = self.get_irc_user_from_telegram(saved_from_peer.user_id).irc_nick
            else:
               secondary_name = ''
               space2 = ''

        return '|Fwd{}{}{}{}| '.format(space, forwarded_peer_name, space2, secondary_name)

    async def handle_telegram_media(self, message, user, mid):
        caption = ' | {}'.format(message.message) if message.message else ''
        to_download = True
        media_url_or_data = ''
        size = 0
        filename = None

        def scan_doc_attributes(document):
            attrib_file = attrib_av = filename = None
            size = document.size
            h_size = get_human_size(size)
            for x in document.attributes:
                if isinstance(x, tgty.DocumentAttributeVideo) or isinstance(x, tgty.DocumentAttributeAudio):
                    attrib_av = x
                if isinstance(x, tgty.DocumentAttributeFilename):
                    attrib_file = x
            filename = attrib_file.file_name if attrib_file else None

            return size, h_size, attrib_av, filename

        if isinstance(message.media, tgty.MessageMediaWebPage):
            to_download = False
            if isinstance(message.media.webpage, tgty.WebPage):
                # web
                return await self.handle_webpage(message.media.webpage, message, mid)
            elif isinstance(message.media.webpage, tgty.WebPagePending):
                media_type = 'webpending'
                media_url_or_data = message.message
                caption = ''
                self.webpending[message.media.webpage.id] = message
            else:
                media_type = 'webunknown'
                media_url_or_data = message.message
                caption = ''
        elif message.photo:
            size, media_type = self.scan_photo_attributes(message.media.photo)
        elif message.audio:
            size, h_size, attrib_audio, filename = scan_doc_attributes(message.media.document)
            dur = get_human_duration(attrib_audio.duration) if attrib_audio else ''
            per = attrib_audio.performer or ''
            tit = attrib_audio.title or ''
            theme = ',{}/{}'.format(per, tit) if per or tit else ''
            media_type = 'audio:{},{}{}'.format(h_size, dur, theme)
        elif message.voice:
            size, _, attrib_audio, filename = scan_doc_attributes(message.media.document)
            dur = get_human_duration(attrib_audio.duration) if attrib_audio else ''
            media_type = 'rec:{}'.format(dur)
        elif message.video:
            size, h_size, attrib_video, filename = scan_doc_attributes(message.media.document)
            dur = get_human_duration(attrib_video.duration) if attrib_video else ''
            media_type = 'video:{},{}'.format(h_size, dur)
        elif message.video_note:   media_type = 'videorec'
        elif message.gif:          media_type = 'anim'
        elif message.sticker:      media_type = 'sticker'
        elif message.document:
            size, h_size, _, filename = scan_doc_attributes(message.media.document)
            media_type = 'file:{}'.format(h_size)
        elif message.contact:
            media_type = 'contact'
            caption = ''
            to_download = False
            if message.media.first_name:
                media_url_or_data += message.media.first_name + ' '
            if message.media.last_name:
                media_url_or_data += message.media.last_name + ' '
            if message.media.phone_number:
                media_url_or_data += message.media.phone_number

        elif message.game:
            media_type = 'game'
            caption = ''
            to_download = False
            if message.media.game.title:
                media_url_or_data = message.media.game.title

        elif message.geo:
            media_type = 'geo'
            caption = ''
            to_download = False
            if self.geo_url:
                geo_url = ' | ' + self.geo_url
            else:
                geo_url = ''
            lat_long_template = 'lat: {lat}, long: {long}' + geo_url
            media_url_or_data = lat_long_template.format(lat=message.media.geo.lat, long=message.media.geo.long)

        elif message.invoice:
            media_type = 'invoice'
            caption = ''
            to_download = False
            media_url_or_data = ''

        elif message.poll:
            media_type = 'poll'
            caption = ''
            to_download = False
            media_url_or_data = self.handle_poll(message.media.poll)

        elif message.venue:
            media_type = 'venue'
            caption = ''
            to_download = False
            media_url_or_data = ''
        else:
            media_type = 'unknown'
            caption = ''
            to_download = False
            media_url_or_data = message.message

        if to_download:
            relay_attr = (message, user, mid, media_type)
            media_url_or_data = await self.download_telegram_media(message, mid, filename, size, relay_attr)

        return self.format_media(media_type, media_url_or_data, caption)

    def handle_poll(self, poll):
        text = poll.question
        for ans in poll.answers:
            text += '\n* ' + ans.text
        return text

    def handle_target_mine(self, target, user):
        # Add the target of messages sent by self user (me)
        # received in other clients
        target_id, target_type = self.get_peer_id_and_type(target)
        if user is None and target_type == 'user' and target_id != self.id:
           # self user^
           # as sender
            irc_id = self.get_irc_name_from_telegram_id(target_id)
            target_mine = '[T: {}] '.format(irc_id)
        else:
            target_mine = ''
        return target_mine

    async def handle_webpage(self, webpage, message, mid):
        media_type = 'web'
        logo = await self.download_telegram_media(message, mid)
        if is_url_equiv(webpage.url, webpage.display_url):
            url_data = webpage.url
        else:
            url_data = '{} | {}'.format(webpage.url, webpage.display_url)
        if message:
            # sometimes the 1st line of message contains the title, don't repeat it
            message_line = message.message.splitlines()[0]
            if message_line != webpage.title:
                title = webpage.title
            else:
                title = ''
            # extract the URL in the message, don't repeat it
            message_url = extract_url(message.message)
            if is_url_equiv(message_url, webpage.url):
                if is_url_equiv(message_url, webpage.display_url):
                    media_url_or_data = message.message
                else:
                    media_url_or_data = '{} | {}'.format(message.message, webpage.display_url)
            else:
                media_url_or_data = '{} | {}'.format(message.message, url_data)
        else:
            title = webpage.title
            media_url_or_data = url_data

        if title and logo:
            caption = ' | {} | {}'.format(title, logo)
        elif title:
            caption = ' | {}'.format(title)
        elif logo:
            caption = ' | {}'.format(logo)
        else:
            caption = ''

        return self.format_media(media_type, media_url_or_data, caption)

    def format_media(self, media_type, media_url_or_data, caption):
        return '[{}] {}{}'.format(media_type, media_url_or_data, caption)

    def scan_photo_attributes(self, photo):
        size = 0
        sizes = photo.sizes
        ph_size = sizes[-1]
        if isinstance(ph_size, tgty.PhotoSizeProgressive):
            size = ph_size.sizes[-1]
        else:
            for x in sizes:
                if isinstance(x, tgty.PhotoSize):
                    if x.size > size:
                        size = x.size
                        ph_size = x
        if hasattr(ph_size, 'w') and hasattr(ph_size, 'h'):
            media_type = 'photo:{}x{}'.format(ph_size.w, ph_size.h)
        else:
            media_type = 'photo'

        return size, media_type

    async def download_telegram_media(self, message, mid, filename=None, size=0, relay_attr=None):
        if not self.download:
            return ''
        if filename:
            idd_file = add_filename(filename, mid)
            new_file = sanitize_filename(idd_file)
            new_path = os.path.join(self.telegram_media_dir, new_file)
            if os.path.exists(new_path):
                local_path = new_path
            else:
                await self.notice_downloading(size, relay_attr)
                local_path = await message.download_media(new_path)
                if not local_path: return ''
        else:
            await self.notice_downloading(size, relay_attr)
            local_path = await message.download_media(self.telegram_media_dir)
            if not local_path: return ''
            filetype = os.path.splitext(local_path)[1]
            gen_file = str(self.media_cn) + filetype
            idd_file = add_filename(gen_file, mid)
            new_file = sanitize_filename(idd_file)
            self.media_cn += 1
            new_path = os.path.join(self.telegram_media_dir, new_file)

        if local_path != new_path:
            os.replace(local_path, new_path)
        if self.media_url[-1:] != '/':
            self.media_url += '/'
        return self.media_url + new_file

    async def notice_downloading(self, size, relay_attr):
        if relay_attr and size > self.notice_size:
            message, user, mid, media_type = relay_attr
            await self.relay_telegram_message(message, user, '[{}] [{}] [Downloading]'.format(mid, media_type))

class mesg_id:
    def __init__(self, alpha):
        self.alpha = alpha
        self.base = len(alpha)
        self.alphaval = { i:v for v, i in enumerate(alpha) }
        self.mesg_base = {}

    def num_to_id(self, num, neg=''):
        if num < 0: return self.num_to_id(-num, '-')
        (high, low) = divmod(num, self.base)
        if high >= self.base:
            aux = self.num_to_id(high)
            return neg + aux + self.alpha[low]
        else:
            return neg + self.alpha[high] + self.alpha[low]

    def num_to_id_offset(self, peer, num):
        peer_id = self.get_peer_id(peer)
        if peer_id not in self.mesg_base:
            self.mesg_base[peer_id] = num
        return self.num_to_id(num - self.mesg_base[peer_id])

    def id_to_num(self, id, n=1):
        if id:
            if id[0] == '-': return self.id_to_num(id[1:], -1)
            aux = self.alphaval[id[-1:]] * n
            sum = self.id_to_num(id[:-1], n * self.base)
            return sum + aux
        else:
            return 0

    def id_to_num_offset(self, peer, mid):
        peer_id = self.get_peer_id(peer)
        if peer_id in self.mesg_base:
            id_rel = self.id_to_num(mid)
            id = id_rel + self.mesg_base[peer_id]
        else:
            id = None
        return id

    def get_peer_id(self, peer):
        if isinstance(peer, tgty.PeerChannel):
            id = peer.channel_id
        elif isinstance(peer, tgty.PeerChat):
            id = peer.chat_id
        elif isinstance(peer, tgty.PeerUser):
            id = peer.user_id
        else:
            id = peer
        return id
