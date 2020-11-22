
import collections
import logging
import re
import socket

import tornado.httpclient
import tornado.ioloop

# Local modules

from utils import chunks

# Configuration

UPDATE_CHANNEL_VOICES_DELAY = 300

# IRC Regular Expressions

IRC_NICK_RX    = re.compile(r'NICK :(?P<nick>[^\n\r]+)')
IRC_PASS_RX    = re.compile(r'PASS :(?P<app_id>[^\s]+) (?P<app_hash>[^\n\r]+)')
IRC_PING_RX    = re.compile(r'PING (?P<payload>[^\n\r]+)')
IRC_PRIVMSG_RX = re.compile(r'PRIVMSG (?P<nick>[^\s]+) :(?P<message>[^\n\r]+)')
IRC_USER_RX    = re.compile(r'USER (?P<username>[^\s]+) [^\s]+ [^\s]+ :(?P<realname>[^\n\r]+)')
IRC_JOIN_RX    = re.compile(r'JOIN (?P<channel>[^\s]+)')

# IRC Handler

class IRCHandler(object):
    def __init__(self, config_dir):
        self.logger     = logging.getLogger()
        self.ioloop     = tornado.ioloop.IOLoop.current()
        self.hostname   = socket.gethostname()
        self.config_dir = config_dir

        # Initialize IRC
        self.initialize_irc()


    async def run(self, stream, address):
        self.stream = stream
        self.address    = '{}:{}'.format(address[0], address[1])

        self.logger.debug('Running client connection from %s', self.address)

        while True:
            message = await self.stream.read_until(b'\n')
            message = message.decode().rstrip()
            self.logger.debug(message)

            for pattern, handler in self.irc_handlers:
                matches = pattern.match(message)
                if matches:
                    await handler(**matches.groupdict())

    def set_telegram(self, tg):
        self.tg = tg

    # IRC

    def initialize_irc(self):
        self.irc_handlers = (
            (IRC_NICK_RX   , self.handle_irc_nick),
            (IRC_PASS_RX   , self.handle_irc_pass),
            (IRC_PING_RX   , self.handle_irc_ping),
            (IRC_PRIVMSG_RX, self.handle_irc_privmsg),
            (IRC_USER_RX   , self.handle_irc_user),
            (IRC_JOIN_RX   , self.handle_irc_join),
        )
        self.iid_to_tid   = {}
        self.irc_channels = collections.defaultdict(set)
        self.irc_nick     = None
        self.irc_voices   = collections.defaultdict(set)

    def get_irc_user_mask(self, nick):
        return '{}!{}@{}'.format(nick, nick, self.hostname)

    async def send_irc_command(self, command):
        self.logger.debug('Send IRC Command: %s', command)
        command = command + '\r\n'
        self.stream.write(command.encode())

    async def handle_irc_nick(self, nick):
        self.logger.debug('Handling NICK: %s', nick)

        if self.irc_nick in self.iid_to_tid:
            tid = self.iid_to_tid[self.irc_nick]
            self.tg.tid_to_iid[tid]  = nick
            self.iid_to_tid[nick] = tid

        self.irc_nick = nick

    async def handle_irc_user(self, username, realname):
        self.logger.debug('Handling USER: %s, %s', username, realname)

        self.irc_nick = username

        await self.send_irc_command(':{} 001 {} :{}'.format(
            self.hostname, self.irc_nick, 'Welcome to irgramd'
        ))
        await self.send_irc_command(':{} 376 {} :{}'.format(
            self.hostname, self.irc_nick, 'End of MOTD command'
        ))

    async def handle_irc_join(self, channel):
        self.logger.debug('Handling JOIN: %s', channel)

        await self.join_irc_channel(self.irc_nick, channel, True)

    async def handle_irc_pass(self, app_id, app_hash):
        self.logger.debug('Handling PASS: %s %s', app_id, app_hash)

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
        await self.tg.telegram_client.send_message(telegram_id, message)

    async def join_irc_channel(self, nick, channel, full_join=False):
        self.irc_channels[channel].add(nick)

        # Join Channel
        await self.send_irc_command(':{} JOIN :{}'.format(
            self.get_irc_user_mask(nick), channel
        ))

        if not full_join:
            return

        # Add all users to channel
        tid           = self.iid_to_tid[channel]
        nicks, voices = await self.tg.get_telegram_channel_participants(tid)

        # Set channel topic
        topic = (await self.tg.telegram_client.get_entity(tid)).title
        await self.send_irc_command(':{} TOPIC {} :{}'.format(
            self.get_irc_user_mask(nick), channel, topic
        ))

        # Send NAMESLIST
        for chunk in chunks(nicks, 25, ''):
            await self.send_irc_command(':{} 353 {} = {} :{}'.format(
                self.hostname, self.irc_nick, channel, ' '.join(chunk)
            ))

        # Update voices
        await self.update_channel_voices(channel, voices)

    async def part_irc_channel(self, nick, channel):
        self.irc_channels[channel].remove(nick)
        await self.send_irc_command(':{} PART {} :'.format(
            self.get_irc_user_mask(nick), channel
        ))

    async def update_channel_voices(self, channel, voices=None):
        # Get voices for channel if not provided
        if not voices:
            tid       = self.iid_to_tid[channel]
            _, voices = await self.tg.get_telegram_channel_participants(tid)

        # Add new voices
        for nick in voices:
            if nick not in self.irc_voices[channel]:
                self.irc_voices[channel].add(nick)
                await self.send_irc_command(':{} MODE {} +v {}'.format(
                    self.hostname, channel, nick,
                ))

        # Remove old voices
        for nick in self.irc_voices[channel].difference(voices):
            self.irc_voices[channel].remove(nick)
            await self.send_irc_command(':{} MODE {} -v {}'.format(
                self.hostname, channel, nick,
            ))

        self.ioloop.call_later(UPDATE_CHANNEL_VOICES_DELAY, self.update_channel_voices, channel)

