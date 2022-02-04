
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
from utils import chunks, set_replace, split_lines

# Constants

SRV = None
ALL_PARAMS = 16
VALID_IRC_NICK_FIRST_CHARS   = string.ascii_letters + '[]\`_^{|}'
VALID_IRC_NICK_CHARS         = VALID_IRC_NICK_FIRST_CHARS + string.digits + '-'

# IRC Regular Expressions

PREFIX          = r'(?ai)(:[^ ]+ +|)'
IRC_JOIN_RX     = re.compile(PREFIX + r'JOIN( +:| +|\n)(?P<channels>[^\n ]+|)')
IRC_LIST_RX     = re.compile(PREFIX + r'LIST( +:| +|\n)(?P<channels>[^\n ]+|)')
IRC_MODE_RX     = re.compile(PREFIX + r'MODE( +|\n)(?P<target>[^ ]+( +|\n)|)(?P<mode>[^ ]+( +|\n)|)(?P<arguments>[^\n]+|)')
IRC_MOTD_RX     = re.compile(PREFIX + r'MOTD( +:| +|\n)(?P<target>[^\n ]+|)')
IRC_NAMES_RX    = re.compile(PREFIX + r'NAMES( +:| +|\n)(?P<channels>[^\n ]+|)')
IRC_NICK_RX     = re.compile(PREFIX + r'NICK( +:| +|\n)(?P<nick>[^\n ]+|)')
IRC_PART_RX     = re.compile(PREFIX + r'PART( +|\n)(?P<channels>[^ ]+|)( +:| +|\n|)(?P<reason>[^\n]+|)')
IRC_PASS_RX     = re.compile(PREFIX + r'PASS( +:| +|\n)(?P<password>[^\n ]+|)')
IRC_PING_RX     = re.compile(PREFIX + r'PING( +:| +|\n)(?P<payload>[^\n]+|)')
IRC_PRIVMSG_RX  = re.compile(PREFIX + r'PRIVMSG( +|\n)(?P<target>[^ ]+)( +:| +|\n)(?P<message>[^\n]+|)')
IRC_QUIT_RX     = re.compile(PREFIX + r'QUIT( +:| +|\n)(?P<reason>[^\n]+|)')
IRC_TOPIC_RX    = re.compile(PREFIX + r'TOPIC( +:| +|\n)(?P<channel>[^\n ]+|)')
IRC_USER_RX     = re.compile(PREFIX + r'USER( +|\n)(?P<username>[^ ]+) +[^ ]+ +[^ ]+( +:| +|\n)(?P<realname>[^\n]+|)')
IRC_USERHOST_RX = re.compile(PREFIX + r'USERHOST( +|\n)(?P<nick1>[^ ]+( +|\n)|)(?P<nick2>[^ ]+( +|\n)|)(?P<nick3>[^ ]+( +|\n)|)(?P<nick4>[^ ]+( +|\n)|)(?P<nick5>[^\n]+|)')
IRC_VERSION_RX  = re.compile(PREFIX + r'VERSION( +:| +|\n)(?P<target>[^\n ]+|)')
IRC_WHO_RX      = re.compile(PREFIX + r'WHO( +:| +|\n)(?P<target>[^\n ]+|)')
IRC_WHOIS_RX    = re.compile(PREFIX + r'WHOIS( +:| +|\n)(?P<nicks>[^\n ]+|)')

# IRC Handler

class IRCHandler(object):
    def __init__(self, settings):
        self.logger     = logging.getLogger()
        self.ioloop     = tornado.ioloop.IOLoop.current()
        self.hostname   = socket.gethostname()
        self.conf = settings
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
                user.stream = None
                reason = user.close_reason if user.close_reason else ':Client disconnect'
                await self.send_users_irc(user, 'QUIT', (reason,))
                if user in self.users.values():
                    del self.users[user.irc_nick.lower()]
                    user.del_from_channels(self)
                del user
                break
            message = message.decode().replace('\r','\n')
            self.logger.debug(message)

            for pattern, handler, register_required, num_params_required in self.irc_handlers:
                matches = pattern.match(message)
                if matches:
                    if user.registered or not register_required:
                        params = matches.groupdict()
                        # Remove possible extra characters in parameters
                        params = {x:y.strip() for x,y in params.items()}
                        num_params = len([x for x in params.values() if x])
                        num_params_expected = len(params.keys())
                        if num_params >= self.num_params_necessary(num_params_required,
                                                                   num_params_expected):
                            await handler(user, **params)
                        else:
                            await self.reply_code(user, 'ERR_NEEDMOREPARAMS')
                    else:
                        await self.reply_code(user, 'ERR_NOTREGISTERED', ('',), '*')
                    break

            if not matches and user.registered:
                await self.reply_code(user, 'ERR_UNKNOWNCOMMAND')

    def set_telegram(self, tg):
        self.tg = tg

    # IRC

    def initialize_irc(self):
        self.irc_handlers = (
            # pattern              handle           register_required   num_params_required
            (IRC_JOIN_RX,     self.handle_irc_join,     True,             ALL_PARAMS),
            (IRC_LIST_RX,     self.handle_irc_list,     True,             0),
            (IRC_MODE_RX,     self.handle_irc_mode,     True,             1),
            (IRC_MOTD_RX,     self.handle_irc_motd,     True,             0),
            (IRC_NAMES_RX,    self.handle_irc_names,    True,             ALL_PARAMS),
            (IRC_NICK_RX,     self.handle_irc_nick,     False,            ALL_PARAMS),
            (IRC_PART_RX,     self.handle_irc_part,     True,             1),
            (IRC_PASS_RX,     self.handle_irc_pass,     False,            ALL_PARAMS),
            (IRC_PING_RX,     self.handle_irc_ping,     True,             ALL_PARAMS),
            (IRC_PRIVMSG_RX,  self.handle_irc_privmsg,  True,             ALL_PARAMS),
            (IRC_QUIT_RX,     self.handle_irc_quit,     False,            0),
            (IRC_TOPIC_RX,    self.handle_irc_topic,    True,             ALL_PARAMS),
            (IRC_USER_RX,     self.handle_irc_user,     False,            ALL_PARAMS),
            (IRC_USERHOST_RX, self.handle_irc_userhost, True,             1),
            (IRC_VERSION_RX,  self.handle_irc_version,  True,             0),
            (IRC_WHO_RX,      self.handle_irc_who,      True,             ALL_PARAMS),
            (IRC_WHOIS_RX,    self.handle_irc_whois,    True,             ALL_PARAMS),
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
        current = user.irc_nick.lower() if user.irc_nick else None
        if ni == current:
            return
        if not user.valid_nick(nick):
            await self.reply_code(user, 'ERR_ERRONEUSNICKNAME', (nick,), '*')
        elif ni in self.users.keys():
            await self.reply_code(user, 'ERR_NICKNAMEINUSE', (nick,), '*')
        elif user.pam_auth(nick, self.conf['pam'], self.conf['pam_group'], user.recv_pass) \
             or user.local_auth(nick, self.conf['irc_nicks'], user.recv_pass, self.conf['irc_password'], self.conf['pam']):
            if user.registered:
                # rename
                await self.send_users_irc(user, 'NICK', (nick,))
                del self.users[current]
                for ch in self.irc_channels.keys():
                    set_replace(self.irc_channels[ch], current, ni)
                    set_replace(self.irc_channels_ops[ch], current, ni)
                    set_replace(self.irc_channels_founder[ch], current, ni)
            user.irc_nick = nick
            self.users[ni] = user
            if not user.registered and user.irc_username:
                user.registered = True
                await self.send_greeting(user)
        else:
            await self.reply_code(user, 'ERR_PASSWDMISMATCH')

    async def handle_irc_userhost(self, user, **nicks):
        niv = nicks.values()
        self.logger.debug('Handling USERHOST: %s', str(tuple(niv)))

        reply = ''
        sep = ''
        away = '+'
        for ni in niv:
            n = ni.lower()
            if n in self.users.keys():
                usr = self.users[n]
                oper = '*' if usr.oper else ''
                reply += '{}{}{}={}{}@{}'.format(sep, usr.irc_nick, oper, away, usr.irc_username, usr.address)
                if not sep: sep = ' '
        if reply:
           await self.reply_code(user, 'RPL_USERHOST', (reply,))

    async def handle_irc_user(self, user, username, realname):
        self.logger.debug('Handling USER: %s, %s', username, realname)

        user.irc_username = username
        user.irc_realname = realname
        if user.irc_nick:
            user.registered = True
            await self.send_greeting(user)

    async def handle_irc_join(self, user, channels):
        self.logger.debug('Handling JOIN: %s', channels)

        if channels == '0':
            for channel in self.irc_channels.keys():
                if user.irc_nick in self.irc_channels[channel]:
                    await self.part_irc_channel(user, channel, '')
        else:
            for channel in channels.split(','):
                if channel.lower() in self.irc_channels.keys():
                    await self.join_irc_channel(user, channel, True)
                else:
                    await self.reply_code(user, 'ERR_NOSUCHCHANNEL', (channel,))

    async def handle_irc_part(self, user, channels, reason):
        self.logger.debug('Handling PART: %s, %s', channels, reason)

        for channel in channels.split(','):
            chan = channel.lower()
            if chan in self.irc_channels.keys():
                if user.irc_nick in self.irc_channels[chan]:
                    await self.part_irc_channel(user, channel, reason)
                else:
                    await self.reply_code(user, 'ERR_NOTONCHANNEL', (channel,))
            else:
                await self.reply_code(user, 'ERR_NOSUCHCHANNEL', (channel,))

    async def handle_irc_list(self, user, channels):
        self.logger.debug('Handling LIST: %s', channels)

        if channels:
            chans = channels.split(',')
        else:
            chans = self.irc_channels.keys()

        await self.reply_code(user, 'RPL_LISTSTART')
        for channel in chans:
            chan = channel.lower()
            if chan in self.irc_channels.keys():
                real_chan = self.get_realcaps_name(chan)
                users_count = len(self.irc_channels[chan])
                topic = await self.tg.get_channel_topic(chan, [None])
                await self.reply_code(user, 'RPL_LIST', (real_chan, users_count, topic))
        await self.reply_code(user, 'RPL_LISTEND')

    async def handle_irc_names(self, user, channels):
        self.logger.debug('Handling NAMES: %s', channels)

        for channel in channels.split(','):
            await self.irc_namelist(user, channel)

    async def handle_irc_mode(self, user, target, mode, arguments):
        self.logger.debug('Handling MODE: %s, %s, %s', target, mode, arguments)

        if not mode:
            tgt = target.lower()
            if tgt in self.users.keys():
                if tgt == user.irc_nick:
                    await self.mode_user(user, user, False)
                else:
                    await self.reply_code(user, 'ERR_USERSDONTMATCH')
            elif tgt[0] == '#':
                if tgt in self.irc_channels.keys():
                    await self.mode_channel(user, target, False)
                else:
                    await self.reply_code(user, 'ERR_NOSUCHCHANNEL', (target,))
            else:
                await self.reply_code(user, 'ERR_NOSUCHNICK', (target,))

    async def handle_irc_motd(self, user, target):
        self.logger.debug('Handling MOTD: %s', target)

        if not target or target == self.hostname:
            await self.send_motd(user)
        else:
            await self.reply_code(user, 'ERR_NOSUCHSERVER', (target,))

    async def handle_irc_topic(self, user, channel):
        self.logger.debug('Handling TOPIC: %s', channel)

        chan = channel.lower()
        real_chan = self.get_realcaps_name(chan)
        await self.irc_channel_topic(user, real_chan, [None])

    async def handle_irc_ping(self, user, payload):
        self.logger.debug('Handling PING: %s', payload)

        await self.reply_command(user, SRV, 'PONG', (self.hostname, payload))

    async def handle_irc_who(self, user, target):
        self.logger.debug('Handling WHO: %s', target)
        tgt = target.lower()
        if tgt in self.irc_channels.keys():
            users = self.irc_channels[tgt]
            chan = self.get_realcaps_name(tgt)
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
        self.logger.debug('Handling WHOIS: %s', nicks)
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

    async def handle_irc_version(self, user, target):
        self.logger.debug('Handling VERSION: %s', target)

        tgt = target.lower()
        if not tgt or tgt == self.hostname or tgt in self.users.keys():
            await self.reply_code(user, 'RPL_VERSION', (VERSION, self.hostname))
            await self.send_isupport(user)
        else:
            await self.reply_code(user, 'ERR_NOSUCHSERVER', (target,))

    async def handle_irc_privmsg(self, user, target, message):
        self.logger.debug('Handling PRIVMSG: %s, %s', target, message)

        tgl = target.lower()
        # Echo channel messages from IRC to other IRC connections
        # because they won't receive event from Telegram
        if tgl in self.irc_channels.keys():
            await self.send_msg_others(user, tgl, message)

        if tgl == user.irc_nick:
            tgt = self.tg.tg_username.lower()
            # Echo message to the user him/herself in IRC
            # because no event will be received from Telegram
            await self.send_msg(user, None, message)
        else:
            tgt = tgl

        if tgt in self.iid_to_tid:
            telegram_id = self.iid_to_tid[tgt]
            await self.tg.telegram_client.send_message(telegram_id, message)
        else:
            await self.reply_code(user, 'ERR_NOSUCHNICK', (target,))

    async def handle_irc_quit(self, user, reason):
        self.logger.debug('Handling TOPIC: %s', reason)

        await self.reply_command(user, SRV, 'ERROR', (':Client disconnect',))
        user.close_reason = ':' + reason
        user.stream.close()

    # IRC functions

    async def send_msg(self, source, target, message):
        messages = split_lines(message)
        tgt = target.lower() if target else ''
        is_chan = tgt in self.irc_channels.keys()
        # source None (False): it's self Telegram user, see [1]
        source_mask = source.get_irc_mask() if source else ''
        for msg in messages:
            if is_chan:
                irc_users = (u for u in self.users.values() if u.stream and u.irc_nick in self.irc_channels[tgt])
            else:
                irc_users = (u for u in self.users.values() if u.stream)

            for irc_user in irc_users:
                await self.send_privmsg(irc_user, source_mask, target, msg)

    async def send_msg_others(self, source, target, message):
        source_mask = source.get_irc_mask()
        is_chan = target in self.irc_channels.keys()
        if is_chan:
            irc_users = (u for u in self.users.values() if u.stream and u.irc_nick != source.irc_nick
                                                        and u.irc_nick in self.irc_channels[target])
        else:
            irc_users = (u for u in self.users.values() if u.stream and u.irc_nick != source.irc_nick)

        for irc_user in irc_users:
            await self.send_privmsg(irc_user, source_mask, target, message)

    async def send_privmsg(self, user, source_mask, target, msg):
        # reference [1]
        src_mask = source_mask if source_mask else user.get_irc_mask()
        # target None (False): it's private, not a channel
        tgt = target if target else user.irc_nick
        await self.send_irc_command(user, ':{} PRIVMSG {} :{}'.format(src_mask, tgt, msg))

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
        await self.send_isupport(user)
        await self.send_motd(user)
        await self.mode_user(user, user, True)

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

    async def send_isupport(self, user):
        await self.reply_code(user, 'RPL_ISUPPORT', (CHAN_MAX_LENGHT, NICK_MAX_LENGTH))

    async def send_users_irc(self, prfx, command, params):
        for usr in [x for x in self.users.values() if x.stream]:
            await self.reply_command(usr, prfx, command, params)

    async def mode_user(self, user, usr, com):
        modes = ''
        if usr.oper: modes += 'o'
        if usr.tls: modes += 'S'
        if modes: modes = '+' + modes
        if com:
            await self.reply_command(user, usr, 'MODE', (usr.irc_nick, modes))
        else:
            await self.reply_code(user, 'RPL_UMODEIS', (modes,))

    async def mode_channel(self, user, channel, com):
        modes = '+nt'
        if com:
            await self.reply_command(user, user, 'MODE', (channel, modes))
        else:
            await self.reply_code(user, 'RPL_CHANNELMODEIS', (channel, modes,''))

    async def join_irc_channel(self, user, channel, full_join=False):
        entity_cache = [None]
        chan = channel.lower()
        real_chan = self.get_realcaps_name(chan)

        if full_join: self.irc_channels[chan].add(user.irc_nick)

        # Notify IRC users in this channel
        for usr in [self.users[x.lower()] for x in self.irc_channels[chan] if self.users[x.lower()].stream]:
            await self.reply_command(usr, user, 'JOIN', (real_chan,))

        if not full_join:
            return

        op = self.get_irc_op(self.tg.tg_username, channel)
        if op == '@': self.irc_channels_ops[chan].add(user.irc_nick)
        elif op == '~': self.irc_channels_founder[chan].add(user.irc_nick)

        date = await self.tg.get_channel_creation(channel, entity_cache)
        await self.reply_code(user, 'RPL_CREATIONTIME', (real_chan, date))
        await self.irc_channel_topic(user, real_chan, entity_cache)
        await self.irc_namelist(user, real_chan)

    async def part_irc_channel(self, user, channel, reason):
        chan = channel.lower()
        real_chan = self.get_realcaps_name(chan)

        # Notify IRC users in this channel
        for usr in [self.users[x.lower()] for x in self.irc_channels[chan] if self.users[x.lower()].stream]:
            await self.reply_command(usr, user, 'PART', (real_chan, reason))

        self.irc_channels[chan].remove(user.irc_nick)
        self.irc_channels_ops[chan].discard(user.irc_nick)
        self.irc_channels_founder[chan].discard(user.irc_nick)

    async def irc_channel_topic(self, user, channel, entity_cache):
        chan = channel.lower()
        topic = await self.tg.get_channel_topic(chan, entity_cache)
        timestamp = await self.tg.get_channel_creation(chan, entity_cache)
        founder = list(self.irc_channels_founder[chan])[0]
        await self.reply_code(user, 'RPL_TOPIC', (channel, topic))
        await self.reply_code(user, 'RPL_TOPICWHOTIME', (channel, founder, timestamp))

    async def irc_namelist(self, user, channel):
        nicks = [self.get_irc_op(x, channel) + x for x in self.irc_channels[channel.lower()]]
        status = '='
        for chunk in chunks(nicks, 25, ''):
            await self.reply_code(user, 'RPL_NAMREPLY', (status, channel, ' '.join(chunk)))
        await self.reply_code(user, 'RPL_ENDOFNAMES', (channel,))

    def get_irc_op(self, nick, channel):
        chan = channel.lower()
        if chan in self.irc_channels.keys():
            if nick in self.irc_channels_ops[chan]:
                return '@'
            if nick in self.irc_channels_founder[chan]:
                return '~'
        return ''

    def get_realcaps_name(self, name):
        # name must be in lower
        return self.tg.tid_to_iid[self.iid_to_tid[name]]

    def num_params_necessary(self, num_params_required, num_params_expected):
        if num_params_required == ALL_PARAMS:
            npn = num_params_expected
        else:
            npn = num_params_required
        return npn

class IRCUser(object):
    def __init__(self, stream, address, irc_nick=None, username='', realname=None):
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
        self.close_reason = ''

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
                    return False
            return True
        else: return False

    def del_from_channels(self, irc, channels=None):
        for chan in channels if channels else irc.irc_channels.keys():
            irc.irc_channels[chan].discard(self.irc_nick)
            irc.irc_channels_ops[chan].discard(self.irc_nick)
            irc.irc_channels_founder[chan].discard(self.irc_nick)

    def pam_auth(self, nick, pam, pam_group, recv_pass):
        if not pam: return False

        # Check if user is in groups (main or others)
        if pam_group:
            import pwd
            import grp
            try:
                user_group_id = pwd.getpwnam(nick).pw_gid
                group_data = grp.getgrnam(pam_group)
                pam_group_id = group_data.gr_gid
                group_members = group_data.gr_mem
                check_group = user_group_id == pam_group_id \
                              or nick in group_members
            except:
                check_group = False
            if not check_group: return False

        # Check user authentication (via PAM)
        import PAM
        def pam_conv(auth, query_list, userData):
            resp = []
            resp.append((recv_pass, 0))
            return resp
        p = PAM.pam()
        p.start('passwd')
        p.set_item(PAM.PAM_USER, nick)
        p.set_item(PAM.PAM_CONV, pam_conv)
        try:
            p.authenticate()
            p.acct_mgmt()
        except:
            return False
        else:
            return True

    def local_auth(self, nick, nicks, recv_pass, irc_pass, pam):
        return ( not pam
                 and nick in nicks
                 and recv_pass == irc_pass
               )
