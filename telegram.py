
import logging
import os
import datetime
import re
import telethon
from telethon import types as tgty

# Local modules

from include import CHAN_MAX_LENGHT, NICK_MAX_LENGTH
from irc import IRCUser
from utils import sanitize_filename

# Constants

TL_TYPES_IDENT = re.compile(r"<class 'telethon.tl.types.([^']+)'>")
FILENAME_INVALID_CHARS = re.compile('[/{}<>()"\'\\|&]')

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
        self.media_url  = settings['media_url']
        self.media_cn   = 0
        self.irc        = irc
        self.authorized = False
        self.id	= None
        self.tg_username = None
        self.channels_date = {}
        self.mid = mesg_id('0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ!#$%+./_~')

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

    async def get_telegram_display_name_me(self):
        tg_user = await self.telegram_client.get_me()
        return self.get_telegram_display_name(tg_user)

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

    async def get_channel_topic(self, channel, entity_cache):
        tid = self.get_tid(channel)
        # entity_cache should be a list to be a persistent and by reference value
        if entity_cache[0]:
            entity = entity_cache[0]
        else:
            entity = await self.telegram_client.get_entity(tid)
            entity_cache[0] = entity
        entity_type = self.get_entity_type(entity)
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

    def get_entity_type(self, entity):
        return TL_TYPES_IDENT.match(str(type(entity))).groups()[0]

    async def handle_telegram_message(self, event):
        self.logger.debug('Handling Telegram Message: %s', event)

        if self.mid.mesg_base is None:
            self.mid.mesg_base = event.message.id

        user = self.get_irc_user_from_telegram(event.sender_id)
        mid = self.mid.num_to_id(event.message.id - self.mid.mesg_base)

        if event.message.media:
            text = await self.handle_telegram_media(event.message)
        else:
            text = event.message.message

        message = '[{}] {}'.format(mid, text)

        if event.message.is_private:
            await self.handle_telegram_private_message(user, message)
        else:
            await self.handle_telegram_channel_message(event, user, message)

    async def handle_telegram_private_message(self, user, message):
        self.logger.debug('Handling Telegram Private Message: %s, %s', user, message)

        await self.irc.send_msg(user, None, message)

    async def handle_telegram_channel_message(self, event, user, message):
        self.logger.debug('Handling Telegram Channel Message: %s', event)

        entity  = await event.message.get_chat()
        channel = await self.get_irc_channel_from_telegram_id(event.message.chat_id, entity)
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

    async def handle_telegram_media(self, message):
        caption = ' | {}'.format(message.message) if message.message else ''
        to_download = True
        media_url_or_data = ''

        if message.web_preview:
            media_type = 'web'
            logo = await self.download_telegram_media(message)
            to_download = False
            media_url_or_data = message.message
            if message.media.webpage.title and logo:
                caption = ' | {} | {}'.format(message.media.webpage.title, logo)
            elif message.media.webpage.title:
                caption = ' | {}'.format(message.media.webpage.title)
            elif logo:
                caption = ' | {}'.format(logo)
            else:
                caption = ''

        elif message.photo:
            size = message.media.photo.sizes[-1]
            if hasattr(size, 'w') and hasattr(size, 'h'):
                media_type = 'photo:{}x{}'.format(size.w, size.h)
            else:
                media_type = 'photo'
        elif message.audio:        media_type = 'audio'
        elif message.voice:        media_type = 'rec'
        elif message.video:        media_type = 'video'
        elif message.video_note:   media_type = 'videorec'
        elif message.gif:          media_type = 'anim'
        elif message.sticker:      media_type = 'sticker'
        elif message.document:     media_type = 'file'

        elif message.contact:
            media_type = 'contact'
            caption = ''
            to_download = False
            if message.media.contact.first_name:
                media_url_or_data += message.media.contact.first_name + ' '
            if message.media.contact.last_name:
                media_url_or_data += message.media.contact.last_name + ' '
            if message.media.contact.phone_number:
                media_url_or_data += message.media.contact.phone_number

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
            media_url_or_data = 'lat: {}, long: {}'.format(message.media.geo.lat, message.media.geo.long)

        elif message.invoice:
            media_type = 'invoice'
            caption = ''
            to_download = False
            media_url_or_data = ''

        elif message.poll:
            media_type = 'poll'
            caption = ''
            to_download = False
            media_url_or_data = ''

        elif message.venue:
            media_type = 'venue'
            caption = ''
            to_download = False
            media_url_or_data = ''

        if to_download:
            media_url_or_data = await self.download_telegram_media(message)

        return '[{}] {}{}'.format(media_type, media_url_or_data, caption)

    async def download_telegram_media(self, message):
        local_path = await message.download_media(self.telegram_media_dir)
        if not local_path: return ''

        if message.document:
            new_file = sanitize_filename(os.path.basename(local_path))
        else:
            filetype = os.path.splitext(local_path)[1]
            new_file = str(self.media_cn) + filetype
            self.media_cn += 1

        new_path = os.path.join(self.telegram_media_dir, new_file)
        if local_path != new_path:
            os.replace(local_path, new_path)
        if self.media_url[-1:] != '/':
            self.media_url += '/'
        return self.media_url + new_file

class mesg_id:
    def __init__(self, alpha):
        self.alpha = alpha
        self.base = len(alpha)
        self.alphaval = { i:v for v, i in enumerate(alpha) }
        self.mesg_base = None

    def num_to_id(self, num, neg=''):
        if num < 0: return self.num_to_id(-num, '-')
        (high, low) = divmod(num, self.base)
        if high >= self.base:
            aux = self.num_to_id(high)
            return neg + aux + self.alpha[low]
        else:
            return neg + self.alpha[high] + self.alpha[low]

    def id_to_num(self, id, n=1):
        if id:
            if id[0] == '-': return self.id_to_num(id[1:], -1)
            aux = self.alphaval[id[-1:]] * n
            sum = self.id_to_num(id[:-1], n * self.base)
            return sum + aux
        else:
            return 0
