
import logging
import os
import datetime
import re
import telethon
from telethon import types as tgty

# Local modules

from include import CHAN_MAX_LENGHT, NICK_MAX_LENGTH
from irc import IRCUser

# Constants

TL_TYPES_IDENT = re.compile(r"<class 'telethon.tl.types.([^']+)'>")

# Configuration

# GET API_ID and API_HASH from https://my.telegram.org/apps
# AND PUT HERE BEFORE RUNNING irgramd

TELEGRAM_API_ID             =
TELEGRAM_API_HASH           = ''


    # Telegram

class TelegramHandler(object):
    def __init__(self, irc, settings):
        self.logger     = logging.getLogger()
        self.config_dir = settings['config_dir']
        self.irc        = irc
        self.authorized = False
        self.id	= None
        self.tg_username = None
        self.channels_date = {}

    async def initialize_telegram(self):
        # Setup media folder
        self.telegram_media_dir = os.path.join(self.config_dir, 'media')
        if not os.path.exists(self.telegram_media_dir):
            os.makedirs(self.telegram_media_dir)

        # Setup session folder
        self.telegram_session_dir = os.path.join(self.config_dir, 'session')
        if not os.path.exists(self.telegram_session_dir):
            os.makedirs(self.telegram_session_dir)

        # Construct Telegram client
        telegram_session     = os.path.join(self.telegram_session_dir, 'telegram')
        self.telegram_client = telethon.TelegramClient(telegram_session,
            TELEGRAM_API_ID, TELEGRAM_API_HASH
        )

        # Initialize Telegram ID to IRC nick mapping
        self.tid_to_iid = {}

        # Register Telegram callbacks
        callbacks = (
            (self.handle_telegram_message    , telethon.events.NewMessage),
            (self.handle_telegram_chat_action, telethon.events.ChatAction),
        )
        for handler, event in callbacks:
            self.telegram_client.add_event_handler(handler, event)

        # Start Telegram client
        await self.telegram_client.connect()

        if await self.telegram_client.is_user_authorized():
            self.authorized = True
            await self.init_mapping()

    async def init_mapping(self):
        # Update IRC <-> Telegram mapping
        tg_user = await self.telegram_client.get_me()
        self.id = tg_user.id
        self.tg_username = self.get_telegram_nick(tg_user)
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
                irc_user = IRCUser(None, ('Telegram',), tg_nick, user.id, self.get_telegram_display_name(user))
                self.irc.users[tg_ni] = irc_user
            self.tid_to_iid[user.id] = tg_nick
            self.irc.iid_to_tid[tg_ni] = user.id
        else:
            tg_nick = self.tid_to_iid[user.id]
        return tg_nick

    async def set_irc_channel_from_telegram(self, chat):
        channel = self.get_telegram_channel(chat)
        self.tid_to_iid[chat.id] = channel
        self.irc.iid_to_tid[channel.lower()] = chat.id
        chan = channel.lower()
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

    def get_telegram_channel(self, chat):
        return '#' + chat.title.replace(' ', '-')

    def get_irc_user_from_telegram(self, tid):
        nick = self.tid_to_iid[tid]
        if nick == self.tg_username: return None
        return self.irc.users[nick.lower()]

    async def get_irc_nick_from_telegram_id(self, tid, entity=None):
        if tid not in self.tid_to_iid:
            user = entity or await self.telegram_client.get_entity(tid)
            nick = self.get_telegram_nick(user)
            self.tid_to_iid[tid]  = nick
            self.irc.iid_to_tid[nick] = tid

        return self.tid_to_iid[tid]

    async def get_irc_channel_from_telegram_id(self, tid, entity=None):
        if tid not in self.tid_to_iid:
            chat    = entity or await self.telegram_client.get_entity(tid)
            channel = self.get_telegram_channel(chat)
            self.tid_to_iid[tid]     = channel
            self.irc.iid_to_tid[channel] = tid

        return self.tid_to_iid[tid]

    async def get_telegram_channel_participants(self, tid):
        channel = self.tid_to_iid[tid]
        nicks   = []
        async for user in self.telegram_client.iter_participants(tid):
            user_nick = await self.get_irc_nick_from_telegram_id(user.id, user)

            nicks.append(user_nick)
            self.irc.irc_channels[channel].add(user_nick)

        return nicks

    async def get_telegram_idle(self, irc_nick, tid=None):
        tid = self.get_tid(irc_nick, tid)
        user = await self.telegram_client.get_entity(tid)
        if isinstance(user.status,tgty.UserStatusRecently) or \
           isinstance(user.status,tgty.UserStatusOnline):
            idle = 0
        elif isinstance(user.status,tgty.UserStatusOffline):
            last = user.status.was_online
            current = datetime.datetime.now(datetime.timezone.utc)
            idle = int((current - last).total_seconds())
        elif isinstance(user.status,tgty.UserStatusLastWeek):
            idle = 604800
        elif isinstance(user.status,tgty.UserStatusLastMonth):
            idle = 2678400
        else:
            idle = None
        return idle

    async def is_bot(self, irc_nick, tid=None):
        if self.irc.users[irc_nick].stream:
            bot = False
        else:
            bot = self.irc.users[irc_nick].bot
        if bot == None:
            tid = self.get_tid(irc_nick, tid)
            user = await self.telegram_client.get_entity(tid)
            bot = user.bot
            self.irc.users[irc_nick].bot = bot
        return bot

    async def get_channel_topic(self, channel, entity_cache=[None]):
        tid = self.get_tid(channel)
        if entity_cache[0]:
            entity = entity_cache[0]
        else:
            entity = await self.telegram_client.get_entity(tid)
            entity_cache[0] = entity
        entity_type = self.get_entity_type(entity)
        return 'Telegram ' + entity_type + ' ' + str(tid) + ': ' + entity.title

    async def get_channel_creation(self, channel, entity_cache=[None]):
        tid = self.get_tid(channel)
        if tid in self.channels_date.keys():
            timestamp = self.channels_date[tid]
        else:
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

    def get_entity_type(self, entity):
        return TL_TYPES_IDENT.match(str(type(entity))).groups()[0]

    async def handle_telegram_message(self, event):
        self.logger.debug('Handling Telegram Message: %s', event)

        if event.message.is_private:
            await self.handle_telegram_private_message(event)
        else:
            await self.handle_telegram_channel_message(event)

    async def handle_telegram_private_message(self, event):
        self.logger.debug('Handling Telegram Private Message: %s', event)

        user = self.get_irc_user_from_telegram(event.sender_id)
        message = event.message.message if event.message.message else ''

        await self.irc.send_msg(user, None, message)

    async def handle_telegram_channel_message(self, event):
        self.logger.debug('Handling Telegram Channel Message: %s', event)

        entity  = await event.message.get_chat()
        channel = await self.get_irc_channel_from_telegram_id(event.message.chat_id, entity)

        user = self.get_irc_user_from_telegram(event.sender_id)

        # Format messages with media
        message = event.message.message if event.message.message else ''
#        if event.message.media and (event.message.photo or event.message.gif):
#            message = await self.download_telegram_media(event.message, 'Image')
#            if message:
#                messages.insert(0, message)
#        elif event.message.media and (event.message.sticker):
#            messages.insert(0, 'Sticker: {}'.format(event.message.sticker.id))

        await self.irc.send_msg(user, channel, message)

    async def handle_telegram_chat_action(self, event):
        self.logger.debug('Handling Telegram Chat Action: %s', event)

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
            await self.irc.join_irc_channel(irc_nick, irc_channel, False)
        elif event.user_kicked or event.user_left:
            await self.irc.part_irc_channel(irc_nick, irc_channel)

    async def join_all_telegram_channels(self):
        async for dialog in self.telegram_client.iter_dialogs():
            chat = dialog.entity
            if not isinstance(chat, tgty.User):
                channel = self.get_telegram_channel(chat)
                self.tid_to_iid[chat.id] = channel
                self.irc.iid_to_tid[channel] = chat.id
                await self.irc.join_irc_channel(self.irc.irc_nick, channel, True)

    async def download_telegram_media(self, message, tag):
        local_path = await message.download_media(self.telegram_media_dir)
        return
        if not local_path:
            return

        request  = tornado.httpclient.HTTPRequest(
            url    = 'https://yld.me/paste',
            method = 'POST',
            body   = open(local_path, 'rb').read(),
        )
        response = await tornado.httpclient.AsyncHTTPClient().fetch(request)

        os.unlink(local_path)
        return tag + ': ' + response.body.decode().strip()
