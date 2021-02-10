
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

SRV = None
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
IRC_WHO_RX      = re.compile(PREFIX + r'WHO( +:| +|\n)(?P<target>[^\n]+|)')
IRC_WHOIS_RX    = re.compile(PREFIX + r'WHOIS( +:| +|\n)(?P<nicks>[^\n]+|)')

# IRC Handler

class IRCHandler(object):
    def __init__(self, config_dir):
        self.logger     = logging.getLogger()
        self.ioloop     = tornado.ioloop.IOLoop.current()
        self.hostname   = socket.gethostname()
        self.config_dir = config_dir
        self.users      = {}

        # Initialize IRC
        self.initialize_irc()


    async def run(self, stream, address):
        user = IRCUser(stream, address)

        self.logger.debug('Running client connection from %s:%s', address[0], address[1])

        while True:
            try:
                message = await user.stream.read_until(b'\n')
            except tornado.iostream.StreamClosedError:
                if user in self.users.values():
                    del self.users[user.irc_nick.lower()]
                    user.del_from_channels(self)
                del user
                break
            message = message.decode()
            self.logger.debug(message)
            matched = False

            for pattern, handler, register_required in self.irc_handlers:
                matches = pattern.match(message)
                if matches:
                    matched = True
                    if user.registered or not register_required:
                        params = matches.groupdict()
                        # Remove possible extra characters in parameters
                        params = {x:y.strip() for x,y in params.items()}
                        num_params = len([x for x in params.values() if x])
                        num_params_expected = len(params.keys())
                        if num_params >= num_params_expected:
                            await handler(user, **params)
                        else:
                            await self.reply_code(user, 'ERR_NEEDMOREPARAMS')

            if not matched and user.registered:
                await self.reply_code(user, 'ERR_UNKNOWNCOMMAND')

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
            (IRC_WHO_RX,      self.handle_irc_who,      True),
            (IRC_WHOIS_RX,    self.handle_irc_whois,    True),
        )
        self.iid_to_tid   = {}
        self.irc_channels = collections.defaultdict(set)
        self.irc_channels_ops = collections.defaultdict(set)
        self.irc_channels_founder = collections.defaultdict(set)
        self.start_time   = time.strftime('%a %d %b %Y %H:%M:%S %z')


    async def send_irc_command(self, user, command):
        self.logger.debug('Send IRC Command: %s', command)
        command = command + '\r\n'
        user.stream.write(command.encode())

    # IRC handlers

    async def handle_irc_pass(self, user, password):
        self.logger.debug('Handling PASS: %s %s', password)

        if user.registered:
            await self.reply_code(user, 'ERR_ALREADYREGISTRED')
        else:
            user.recv_pass = password

    async def handle_irc_nick(self, user, nick):
        self.logger.debug('Handling NICK: %s', nick)

        ni = nick.lower()
        if not user.valid_nick(nick):
            await self.reply_code(user, 'ERR_ERRONEUSNICKNAME', (nick,), '*')
        elif ni in self.users.keys():
            await self.reply_code(user, 'ERR_NICKNAMEINUSE', (nick,), '*')
        elif user.password == user.recv_pass:
            if user.registered:
                # rename
                for usr in [x for x in self.users.values() if x.stream]:
                    await self.reply_command(usr, user, 'NICK', (nick,))
                del self.users[user.irc_nick.lower()]
            user.irc_nick = nick
            self.users[ni] = user
            if not user.registered and user.irc_username:
                user.registered = True
                await self.send_greeting(user)
        else:
            await self.reply_code(user, 'ERR_PASSWDMISMATCH')

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

        await self.reply_command(user, SRV, 'PONG', (self.hostname, payload))

    async def handle_irc_who(self, user, target):
        self.logger.debug('Handling WHO: %s', target)
        tgt = target.lower()
        if tgt in self.irc_channels.keys():
            users = self.irc_channels[tgt]
            chan = target
        elif tgt in self.users.keys():
            users = (self.users[tgt],)
            chan = '*'
        else:
            await self.reply_code(user, 'ERR_NOSUCHSERVER', (target,))
            return
        for usr in users:
            if not isinstance(usr,IRCUser):
                usr = self.users[usr.lower()]
            op = self.get_irc_op(usr.irc_nick, chan)
            await self.reply_code(user, 'RPL_WHOREPLY', (chan, usr.irc_username,
                usr.address, self.hostname, usr.irc_nick, op, usr.irc_realname
            ))
        await self.reply_code(user, 'RPL_ENDOFWHO', (chan,))

    async def handle_irc_whois(self, user, nicks):
        self.logger.debug('Handling WHO: %s', nicks)
        for nick in nicks.split(','):
            ni = nick.lower()
            real_ni = self.users[ni].irc_nick
            if ni in self.users.keys():
                usr = self.users[ni]
                await self.reply_code(user, 'RPL_WHOISUSER', (real_ni, usr.irc_username, usr.address, usr.irc_realname))
                await self.reply_code(user, 'RPL_WHOISSERVER', (real_ni, self.hostname))
                chans = usr.get_channels(self)
                if chans: await self.reply_code(user, 'RPL_WHOISCHANNELS', (real_ni, chans))
                idle = await self.tg.get_telegram_idle(ni)
                if idle != None: await self.reply_code(user, 'RPL_WHOISIDLE', (real_ni, idle))
                if usr.oper: await self.reply_code(user, 'RPL_WHOISOPERATOR', (real_ni,))
                if usr.stream: await self.reply_code(user, 'RPL_WHOISACCOUNT', (real_ni,
                                   '{}!{}@Telegram'.format(self.tg.tg_username, self.tg.id
                               )))
                if await self.tg.is_bot(ni):
                    await self.reply_code(user, 'RPL_WHOISBOT', (real_ni,))
                elif usr.tls or not usr.stream:
                    proto = 'TLS' if usr.tls else 'MTProto'
                    server = self.hostname if usr.stream else 'Telegram'
                    await self.reply_code(user, 'RPL_WHOISSECURE', (real_ni, proto, server))
                await self.reply_code(user, 'RPL_ENDOFWHOIS', (real_ni,))
            else:
                await self.reply_code(user, 'ERR_NOSUCHNICK', (nick,))

    async def handle_irc_privmsg(self, user, nick, message):
        self.logger.debug('Handling PRIVMSG: %s, %s', nick, message)

        target = self.tg.tg_username if nick == user.irc_nick else nick
        tgt = target.lower()

        if tgt not in self.iid_to_tid:
            print('TODO: handle error')

        telegram_id = self.iid_to_tid[tgt]
        await self.tg.telegram_client.send_message(telegram_id, message)

    # IRC functions

    async def reply_command(self, user, prfx, comm, params):
        prefix = self.hostname if prfx == SRV else prfx.get_irc_mask()
        p = len(params)
        if p == 1:
            fstri = ':{} {} {}'
        else:
            fstri = ':{} {}' + ((p - 1) * ' {}') + ' :{}'
        await self.send_irc_command(user, fstri.format(prefix, comm, *params))

    async def reply_code(self, user, code, params=None, client=None):
        num, tail = irc_codes[code]
        if params:
            nick = client if client else user.irc_nick
            rest = tail.format(*params)
            stri = ':{} {} {} {}'.format(self.hostname, num, nick, rest)
        else:
            stri = ':{} {} {} :{}'.format(self.hostname, num, user.irc_nick, tail)
        await self.send_irc_command(user, stri)

    async def send_greeting(self, user):
        await self.reply_code(user, 'RPL_WELCOME', (user.irc_nick,))
        await self.reply_code(user, 'RPL_YOURHOST', (self.hostname, VERSION))
        await self.reply_code(user, 'RPL_CREATED', (self.start_time,))
        await self.reply_code(user, 'RPL_MYINFO', (self.hostname, VERSION))
        await self.reply_code(user, 'RPL_ISUPPORT', (str(CHAN_MAX_LENGHT), str(NICK_MAX_LENGTH)))
        await self.send_motd(user)

    async def send_motd(self, user):
        await self.reply_code(user, 'RPL_MOTDSTART', (self.hostname,))
        await self.reply_code(user, 'RPL_MOTD', ('Welcome to the irgramd server',))
        await self.reply_code(user, 'RPL_MOTD', ('',))
        await self.reply_code(user, 'RPL_MOTD', ('This is not a normal IRC server, it\'s a gateway that',))
        await self.reply_code(user, 'RPL_MOTD', ('allows connecting from an IRC client (the program that',))
        await self.reply_code(user, 'RPL_MOTD', ('you are [probably] using right now) to the Telegram instant',))
        await self.reply_code(user, 'RPL_MOTD', ('messaging network as a regular user account (not bot)',))
        await self.reply_code(user, 'RPL_MOTD', ('',))
        await self.reply_code(user, 'RPL_MOTD', ('irgramd is an open source project that you can find on',))
        await self.reply_code(user, 'RPL_MOTD', ('git repository: https://github.com/prsai/irgramd',))
        await self.reply_code(user, 'RPL_MOTD', ('darcs repository: https://src.presi.org/darcs/irgramd',))
        await self.reply_code(user, 'RPL_ENDOFMOTD')

    async def join_irc_channel(self, user, channel, full_join=False):
        chan = channel.lower()
        self.irc_channels[chan].add(user.irc_nick)
        op = self.get_irc_op(self.tg.tg_username, channel)
        if op == '@': self.irc_channels_ops[chan].add(user.irc_nick)
        elif op == '~': self.irc_channels_founder[chan].add(user.irc_nick)

        # Join Channel
        await self.send_irc_command(user, ':{} JOIN :{}'.format(
            user.get_irc_mask(), channel
        ))

        if not full_join:
            return

        # Get all users from channel
        tid = self.iid_to_tid[channel.lower()]
        nicks = self.irc_channels[channel.lower()]

        # Set channel topic
        topic = (await self.tg.telegram_client.get_entity(tid)).title
        await self.send_irc_command(user, ':{} TOPIC {} :{}'.format(
            user.get_irc_mask(), channel, topic
        ))

        # Send NAMESLIST
        for chunk in chunks(nicks, 25, ''):
            await self.send_irc_command(user, ':{} 353 {} = {} :{}'.format(
                self.hostname, user.irc_nick, channel, ' '.join(chunk)
            ))

    async def part_irc_channel(self, user, channel):
        self.irc_channels[channel].remove(user.irc_nick)
        await self.send_irc_command(user, ':{} PART {} :'.format(
            user.get_irc_mask(), channel
        ))

    def get_irc_op(self, nick, channel):
        chan = channel.lower()
        if chan in self.irc_channels.keys():
            if nick in self.irc_channels_ops[chan]:
                return '@'
            if nick in self.irc_channels_founder[chan]:
                return '~'
        return ''

class IRCUser(object):
    def __init__(self, stream, address, irc_nick=None, username=None, realname=None):
        self.stream  = stream
        self.address = address[0]
        self.irc_nick = irc_nick
        self.irc_username = str(username)
        self.irc_realname = realname
        self.registered = False
        self.password = ''
        self.recv_pass = ''
        self.oper = False
        self.tls = False
        self.bot = None

    def get_irc_mask(self):
        return '{}!{}@{}'.format(self.irc_nick, self.irc_username, self.address)

    def get_channels(self, irc):
        res = ''
        for chan in irc.irc_channels.keys():
            if self.irc_nick in irc.irc_channels[chan]:
                res += irc.get_irc_op(self.irc_nick, chan) + chan + ' '
        return res

    def valid_nick(self, nick):
        if len(nick) <= NICK_MAX_LENGTH and nick[0] in VALID_IRC_NICK_FIRST_CHARS:
            for x in nick[1:]:
                if x not in VALID_IRC_NICK_CHARS:
                    return 0
            return 1
        else: return 0

    def del_from_channels(self, irc, channels=None):
        for chan in channels if channels else irc.irc_channels.keys():
            irc.irc_channels[chan].discard(self.irc_nick)
            irc.irc_channels_ops[chan].discard(self.irc_nick)
            irc.irc_channels_founder[chan].discard(self.irc_nick)
