
import collections
import logging
import re
import socket
import string
import time

import tornado.httpclient
import tornado.ioloop

# Local modules

from include import VERSION, CHAN_MAX_LENGHT, NICK_MAX_LENGTH
from irc_replies import irc_codes
from utils import chunks

# Constants

VALID_IRC_NICK_FIRST_CHARS   = string.ascii_letters + '[]\`_^{|}'
VALID_IRC_NICK_CHARS         = VALID_IRC_NICK_FIRST_CHARS + string.digits + '-'

# IRC Regular Expressions

PREFIX          = r'(:[^ ]+ +|)'
IRC_NICK_RX     = re.compile(PREFIX + r'NICK( +:| +|\n)(?P<nick>[^\n]+|)')
IRC_PASS_RX     = re.compile(PREFIX + r'PASS( +:| +|\n)(?P<password>[^\n]+|)')
IRC_PING_RX     = re.compile(PREFIX + r'PING( +:| +|\n)(?P<payload>[^\n]+|)')
IRC_PRIVMSG_RX  = re.compile(PREFIX + r'PRIVMSG( +|\n)(?P<nick>[^ ]+)( +:| +|\n)(?P<message>[^\n]+|)')
IRC_USER_RX     = re.compile(PREFIX + r'USER( +|\n)(?P<username>[^ ]+) +[^ ]+ +[^ ]+( +:| +|\n)(?P<realname>[^\n]+|)')
IRC_JOIN_RX     = re.compile(PREFIX + r'JOIN( +|\n)(?P<channel>[^ ]+)')

# IRC Handler

class IRCHandler(object):
    def __init__(self, config_dir):
        self.logger     = logging.getLogger()
        self.ioloop     = tornado.ioloop.IOLoop.current()
        self.hostname   = socket.gethostname()
        self.config_dir = config_dir
        self.users      = []

        # Initialize IRC
        self.initialize_irc()


    async def run(self, stream, address):
        user = IRCUser(stream, address)
        self.users.append(user)

        self.logger.debug('Running client connection from %s', user.address)

        while True:
            message = await user.stream.read_until(b'\n')
            message = message.decode()
            self.logger.debug(message)
            matched = False

            for pattern, handler, register_required in self.irc_handlers:
                matches = pattern.match(message)
                if matches:
                    matched = True
                    if user.registered or not register_required:
                        params = matches.groupdict()
                        num_params = len([x for x in params.values() if x])
                        num_params_expected = len(params.keys())
                        if num_params >= num_params_expected:
                            await handler(user, **params)
                        else:
                            await self.reply(user, 'ERR_NEEDMOREPARAMS')

            if not matched and user.registered:
                await self.reply(user, 'ERR_UNKNOWNCOMMAND')

    def set_telegram(self, tg):
        self.tg = tg

    # IRC

    def initialize_irc(self):
        self.irc_handlers = (
            # pattern              handle           register_required
            (IRC_NICK_RX,     self.handle_irc_nick,     False),
            (IRC_PASS_RX,     self.handle_irc_pass,     False),
            (IRC_PING_RX,     self.handle_irc_ping,     False),
            (IRC_PRIVMSG_RX,  self.handle_irc_privmsg,  True),
            (IRC_USER_RX,     self.handle_irc_user,     False),
            (IRC_JOIN_RX,     self.handle_irc_join,     True),
        )
        self.iid_to_tid   = {}
        self.irc_channels = collections.defaultdict(set)
        self.start_time   = time.strftime('%a %d %b %Y %H:%M:%S %z')

    def get_irc_user_mask(self, nick):
        return '{}!{}@{}'.format(nick, nick, self.hostname)

    async def send_irc_command(self, user, command):
        self.logger.debug('Send IRC Command: %s', command)
        command = command + '\r\n'
        user.stream.write(command.encode())

    # IRC handlers

    async def handle_irc_pass(self, user, password):
        self.logger.debug('Handling PASS: %s %s', password)

        if user.registered:
            await self.reply(user, 'ERR_ALREADYREGISTRED')
        else:
            user.recv_pass = password

    async def handle_irc_nick(self, user, nick):
        self.logger.debug('Handling NICK: %s', nick)

        if not self.valid_nick(nick):
             await self.reply(user, 'ERR_ERRONEUSNICKNAME')
        elif nick in [x.irc_nick for x in self.users if x is not user]:
            await self.reply(user, 'ERR_NICKNAMEINUSE')
        elif user.password == user.recv_pass:
            user.irc_nick = nick

            if user.irc_nick in self.iid_to_tid:
                tid = self.iid_to_tid[user.irc_nick]
                self.tg.tid_to_iid[tid] = nick
                self.iid_to_tid[nick] = tid

            if not user.registered and user.irc_username:
                user.registered = True
                await self.send_greeting(user)
        else:
            await self.reply(user, 'ERR_PASSWDMISMATCH')

    async def handle_irc_user(self, user, username, realname):
        self.logger.debug('Handling USER: %s, %s', username, realname)

        user.irc_username = username
        user.irc_realname = realname
        if user.irc_nick:
            user.registered = True
            await self.send_greeting(user)

    async def handle_irc_join(self, user, channel):
        self.logger.debug('Handling JOIN: %s', channel)

        await self.join_irc_channel(user, channel, True)

    async def handle_irc_ping(self, user, payload):
        self.logger.debug('Handling PING: %s', payload)
        await self.send_irc_command(user, ':{} PONG {} :{}'.format(
            self.hostname, self.hostname, payload
        ))

    async def handle_irc_privmsg(self, user, nick, message):
        self.logger.debug('Handling PRIVMSG: %s, %s', nick, message)

        if nick not in self.iid_to_tid:
            print('TODO: handle error')

        telegram_id = self.iid_to_tid[nick]
        await self.tg.telegram_client.send_message(telegram_id, message)

    # IRC functions

    async def reply(self, user, code):
        num, tail = irc_codes[code]
        await self.send_irc_command(user, ':{} {} {} :{}'.format(
            self.hostname, num, user.irc_nick, tail
        ))

    async def reply_param(self, user, num, rest):
        await self.send_irc_command(user, ':{} {} {} {}'.format(
            self.hostname, num, user.irc_nick, rest
        ))

    async def send_greeting(self, user):
        num, rest = irc_codes['RPL_WELCOME']
        await self.reply_param(user, num, rest.format(user.irc_nick))
        num, rest = irc_codes['RPL_YOURHOST']
        await self.reply_param(user, num, rest.format(self.hostname, VERSION))
        num, rest = irc_codes['RPL_CREATED']
        await self.reply_param(user, num, rest.format(self.start_time))
        num, rest = irc_codes['RPL_MYINFO']
        await self.reply_param(user, num, rest.format(self.hostname, VERSION))
        num, rest = irc_codes['RPL_ISUPPORT']
        await self.reply_param(user, num, rest.format(str(CHAN_MAX_LENGHT), str(NICK_MAX_LENGTH)))
        await self.send_motd(user)

    async def send_motd(self, user):
        num, rest = irc_codes['RPL_MOTDSTART']
        await self.reply_param(user, num, rest.format(self.hostname))
        num, rest = irc_codes['RPL_MOTD']
        await self.reply_param(user, num, rest.format('Welcome to the irgramd server'))
        await self.reply_param(user, num, rest.format(''))
        await self.reply_param(user, num, rest.format('This is not a normal IRC server, it\'s a gateway that'))
        await self.reply_param(user, num, rest.format('allows connecting from an IRC client (the program that'))
        await self.reply_param(user, num, rest.format('you are [probably] using right now) to the Telegram instant'))
        await self.reply_param(user, num, rest.format('messaging network as a regular user account (not bot)'))
        await self.reply_param(user, num, rest.format(''))
        await self.reply_param(user, num, rest.format('irgramd is an open source project that you can find on'))
        await self.reply_param(user, num, rest.format('git repository: https://github.com/prsai/irgramd'))
        await self.reply_param(user, num, rest.format('darcs repository: https://src.presi.org/darcs/irgramd'))
        await self.reply(user, 'RPL_ENDOFMOTD')

    async def join_irc_channel(self, user, channel, full_join=False):
        self.irc_channels[channel].add(user.irc_nick)

        # Join Channel
        await self.send_irc_command(user, ':{} JOIN :{}'.format(
            self.get_irc_user_mask(user.irc_nick), channel
        ))

        if not full_join:
            return

        # Add all users to channel
        tid           = self.iid_to_tid[channel]
        nicks         = await self.tg.get_telegram_channel_participants(tid)

        # Set channel topic
        topic = (await self.tg.telegram_client.get_entity(tid)).title
        await self.send_irc_command(user, ':{} TOPIC {} :{}'.format(
            self.get_irc_user_mask(user.irc_nick), channel, topic
        ))

        # Send NAMESLIST
        for chunk in chunks(nicks, 25, ''):
            await self.send_irc_command(user, ':{} 353 {} = {} :{}'.format(
                self.hostname, user.irc_nick, channel, ' '.join(chunk)
            ))

    async def part_irc_channel(self, user, channel):
        self.irc_channels[channel].remove(user.irc_nick)
        await self.send_irc_command(user, ':{} PART {} :'.format(
            self.get_irc_user_mask(user.irc_nick), channel
        ))

    def valid_nick(self, nick):
        if len(nick) <= NICK_MAX_LENGTH and nick[0] in VALID_IRC_NICK_FIRST_CHARS:
            for x in nick[1:]:
                if x not in VALID_IRC_NICK_CHARS:
                    return 0
            return 1
        else: return 0

class IRCUser(object):
    def __init__(self, stream, address):
        self.stream  = stream
        self.address = '{}:{}'.format(address[0], address[1])
        self.irc_nick = None
        self.irc_username = None
        self.irc_realname = None
        self.registered = True
        self.password = ''
        self.recv_pass = ''
