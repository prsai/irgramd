#!/usr/bin/env python3

import collections
import itertools
import logging
import os
import re
import socket

import tornado.gen
import tornado.httpclient
import tornado.ioloop
import tornado.options
import tornado.tcpserver

import telethon.utils
from telethon import TelegramClient, events
from telethon.tl.types import User, UserStatusOnline

# Configuration

NICK_MAX_LENGTH   = 20
USER_STATUS_DELAY = 300

# Utilities

def chunks(iterable, n, fillvalue=None):
    args = [iter(iterable)] * n
    return itertools.zip_longest(*args, fillvalue=fillvalue)

# IRC Server

class IRCServer(tornado.tcpserver.TCPServer):
    def __init__(self, address=None, port=6667):
        tornado.tcpserver.TCPServer.__init__(self)

        self.logger  = logging.getLogger()
        self.address = address or '127.0.0.1'
        self.port    = port

        self.logger.setLevel(logging.INFO)

    async def handle_stream(self, stream, address):
        client = IRCClient(stream, address)
        await client.run()

    def run(self):
        self.listen(self.port, self.address)
        self.logger.info('Starting server on %s:%s', self.address, self.port)

        tornado.ioloop.IOLoop.current().start()

# IRC Regular Expressions

IRC_NICK_RX    = re.compile(r'NICK :(?P<nick>[^\n\r]+)')
IRC_PASS_RX    = re.compile(r'PASS :(?P<app_id>[^\s]+) (?P<app_hash>[^\n\r]+)')
IRC_PING_RX    = re.compile(r'PING (?P<payload>[^\n\r]+)')
IRC_PRIVMSG_RX = re.compile(r'PRIVMSG (?P<nick>[^\s]+) :(?P<message>[^\n\r]+)')
IRC_USER_RX    = re.compile(r'USER (?P<username>[^\s]+) 0 \* :(?P<realname>[^\n\r]+)')

# IRC Client

class IRCClient(object):
    def __init__(self, stream, address):
        self.logger     = logging.getLogger()
        self.address    = '{}:{}'.format(address[0], address[1])
        self.stream     = stream
        self.ioloop     = tornado.ioloop.IOLoop.current()
        self.hostname   = socket.gethostname()

        # Initialize configuration directory
        self.config_dir = os.path.expanduser('~/.config/irtelegramd')
        if not os.path.exists(self.config_dir):
            os.makedirs(self.config_dir)

        # Initialize IRC
        self.initialize_irc()

        self.logger.debug('Established client connection from %s', self.address)

    async def run(self):
        self.logger.debug('Running client connection from %s', self.address)

        while True:
            message = await self.stream.read_until(b'\n')
            message = message.decode().rstrip()
            self.logger.debug(message)

            for pattern, handler in self.irc_handlers:
                matches = pattern.match(message)
                if matches:
                    await handler(**matches.groupdict())

    # IRC

    def initialize_irc(self):
        self.irc_handlers = (
            (IRC_NICK_RX   , self.handle_irc_nick),
            (IRC_PASS_RX   , self.handle_irc_pass),
            (IRC_PING_RX   , self.handle_irc_ping),
            (IRC_PRIVMSG_RX, self.handle_irc_privmsg),
            (IRC_USER_RX   , self.handle_irc_user),
        )
        self.iid_to_tid   = {}
        self.irc_channels = collections.defaultdict(set)
        self.irc_nick     = None
        self.irc_online   = set()

    def get_irc_user_mask(self, nick):
        return '{}!{}@{}'.format(nick, nick, self.hostname)

    def schedule_irc_mode_update(self, nick, channel, force=False):
        if nick not in self.irc_online or force:
            self.ioloop.call_later(USER_STATUS_DELAY, self.update_irc_mode, nick, channel)
            self.irc_online.add(nick)

    async def send_irc_command(self, command):
        self.logger.debug('Send IRC Command: %s', command)
        command = command + '\r\n'
        self.stream.write(command.encode())

    async def handle_irc_nick(self, nick):
        self.logger.debug('Handling NICK: %s', nick)

        if self.irc_nick in self.iid_to_tid:
            tid = self.iid_to_tid[self.irc_nick]
            self.tid_to_iid[tid]  = nick
            self.iid_to_tid[nick] = tid

        self.irc_nick = nick

    async def handle_irc_user(self, username, realname):
        self.logger.debug('Handling USER: %s, %s', username, realname)

        await self.send_irc_command(':{} 001 {} :{}'.format(
            self.hostname, self.irc_nick, 'Welcome to IRTelegramD'
        ))
        await self.send_irc_command(':{} 376 {} :{}'.format(
            self.hostname, self.irc_nick, 'End of MOTD command'
        ))

        await self.initialize_telegram()

    async def handle_irc_pass(self, app_id, app_hash):
        self.logger.debug('Handling PASS: %s %s', app_id, app_hash)
        self.telegram_app_id   = int(app_id)
        self.telegram_app_hash = app_hash

    async def handle_irc_ping(self, payload):
        self.logger.debug('Handling PING: %s', payload)
        await self.send_irc_command(':{} PONG :{}'.format(
            self.hostname, payload
        ))

    async def handle_irc_privmsg(self, nick, message):
        self.logger.debug('Handling PRIVMSG: %s, %s', nick, message)

        if nick not in self.iid_to_tid:
            print('TODO: handle error')

        telegram_id = self.iid_to_tid[nick]
        await self.telegram_client.send_message(telegram_id, message)

    async def join_irc_channel(self, nick, channel):
        self.irc_channels[channel].add(nick)

        # Join Channel
        await self.send_irc_command(':{} JOIN :{}'.format(
            self.get_irc_user_mask(nick), channel
        ))

        # Add all users to channel
        tid    = self.iid_to_tid[channel]
        nicks  = []
        voices = []
        async for user in self.telegram_client.iter_participants(tid):
            if user.id not in self.tid_to_iid:
                user_nick = self.get_telegram_nick(user)
                self.tid_to_iid[user.id]   = user_nick
                self.iid_to_tid[user_nick] = user.id
            else:
                user_nick = self.tid_to_iid[user.id]

            if isinstance(user.status, UserStatusOnline):
                voices.append(user_nick)

            nicks.append(user_nick)
            self.irc_channels[channel].add(user_nick)

        # Set channel topic
        topic = (await self.telegram_client.get_entity(tid)).title
        await self.send_irc_command(':{} TOPIC {} :{}'.format(
            self.get_irc_user_mask(nick), channel, topic
        ))

        # Send NAMESLIST
        for chunk in chunks(nicks, 25, ''):
            await self.send_irc_command(':{} 353 {} = {} :{}'.format(
                self.hostname, self.irc_nick, channel, ' '.join(chunk)
            ))

        # Update voices
        for user_nick in voices:
            await self.send_irc_command(':{} MODE {} +v {}'.format(
                self.hostname, channel, user_nick,
            ))

            self.schedule_irc_mode_update(user_nick, channel)

    async def part_irc_channel(self, nick, channel):
        self.irc_channels[channel].remove(nick)
        await self.send_irc_command(':{} PART {} :'.format(
            self.get_irc_user_mask(nick), channel
        ))

    async def update_irc_mode(self, nick, channel):
        tid  = self.iid_to_tid[nick]
        user = await self.telegram_client.get_entity(tid)
        if isinstance(user.status, UserStatusOnline):
            self.schedule_irc_mode_update(nick, channel, True)
        else:
            self.irc_online.remove(nick)
            await self.send_irc_command(':{} MODE {} -v {}'.format(
                self.hostname, channel, nick,
            ))

    # Telegram

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
        telegram_session     = os.path.join(self.telegram_session_dir, self.irc_nick)
        self.telegram_client = TelegramClient(telegram_session,
            self.telegram_app_id,   # TODO: handle error
            self.telegram_app_hash,
        )

        # Initialize Telegram ID to IRC nick mapping
        self.tid_to_iid = {}

        # Register Telegram callbacks
        callbacks = (
            (self.handle_telegram_message    , events.NewMessage),
            (self.handle_telegram_chat_action, events.ChatAction),
        )
        for handler, event in callbacks:
            self.telegram_client.add_event_handler(handler, event)

        # Start Telegram client
        await self.telegram_client.start()

        # Update IRC <-> Telegram mapping
        telegram_me = await self.telegram_client.get_me()
        iid = self.irc_nick
        tid = telegram_me.id
        self.tid_to_iid[tid] = iid
        self.iid_to_tid[iid] = tid

        # Join all Telegram channels
        await self.join_all_telegram_channels()

    def get_telegram_nick(self, user):
        nick = (user.username
                or telethon.utils.get_display_name(user)
                or str(user.id))
        nick = nick.replace(' ', '')[:NICK_MAX_LENGTH]
        while nick in self.iid_to_tid:
            nick += '_'
        return nick

    def get_telegram_channel(self, chat):
        return '#' + chat.title.lower().replace(' ', '-')

    async def handle_telegram_message(self, event):
        self.logger.debug('Handling Telegram Message: %s', event)

        if event.from_id not in self.tid_to_iid:
            user = await self.telegram_client.get_input_entity(event.from_id)
            nick = self.get_telegram_nick(user)
            self.tid_to_iid[user.id] = nick
            self.iid_to_tid[nick]    = user.id

        if event.message.is_private:
            await self.handle_telegram_private_message(event)
        else:
            await self.handle_telegram_channel_message(event)

    async def handle_telegram_private_message(self, event):
        self.logger.debug('Handling Telegram Private Message: %s', event)

        nick = self.tid_to_iid[event.from_id]
        for message in event.message.message.splitlines():
            await self.send_irc_command(':{} PRIVMSG {} :{}'.format(
                self.get_irc_user_mask(nick), self.irc_nick, message
            ))

    async def handle_telegram_channel_message(self, event):
        self.logger.debug('Handling Telegram Channel Message: %s', event)

        # Retrieve IRC channel name from Telegram ID
        if event.message.chat_id not in self.tid_to_iid:
            chat    = await event.message.get_chat()
            channel = self.get_telegram_channel(chat)
            self.tid_to_iid[chat.id] = channel
            self.iid_to_tid[channel] = chat.id
        else:
            channel = self.tid_to_iid[event.message.chat_id]

        # Join IRC channel if not already in it
        if channel not in self.irc_channels:
            await self.join_irc_channel(self.irc_nick, channel)

        nick = self.tid_to_iid[event.from_id]
        if nick not in self.irc_channels[channel]:
            await self.join_irc_channel(nick, channel)

        # Format messages with media
        messages = event.message.message.splitlines() if event.message.message else []
        if event.message.media and (event.message.photo or event.message.gif):
            message = await self.download_telegram_media(event.message, 'Image')
            if message:
                messages.insert(0, message)
        elif event.message.media and (event.message.sticker):
            messages.insert(0, 'Sticker: {}'.format(event.message.sticker.id))

        # Give voice and schedule IRC mode update
        if nick not in self.irc_online:
            await self.send_irc_command(':{} MODE {} +v {}'.format(
                self.hostname, channel, nick,
            ))
            self.schedule_irc_mode_update(nick, channel)

        # Send all messages to IRC
        for message in messages:
            await self.send_irc_command(':{} PRIVMSG {} :{}'.format(
                self.get_irc_user_mask(nick), channel, message
            ))

    async def handle_telegram_chat_action(self, event):
        self.logger.info('Handling Telegram Chat Action: %s', event)

        irc_channel = self.tid_to_iid[event.action_message.to_id.channel_id]
        irc_nick    = self.tid_to_iid[event.action_message.from_id]

        if event.user_added or event.user_joined:
            await self.join_irc_channel(irc_nick, irc_channel)
        elif event.user_kicked or event.user_left:
            await self.part_irc_channel(irc_nick, irc_channel)

    async def join_all_telegram_channels(self):
        async for dialog in self.telegram_client.iter_dialogs():
            chat = dialog.entity
            if not isinstance(chat, User):
                channel = self.get_telegram_channel(chat)
                self.tid_to_iid[chat.id] = channel
                self.iid_to_tid[channel] = chat.id
                await self.join_irc_channel(self.irc_nick, channel)

    async def download_telegram_media(self, message, tag):
        local_path = await message.download_media(self.telegram_media_dir)
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

# Main Execution

if __name__ == '__main__':
    irc_server = IRCServer(port=6668)
    irc_server.run()
