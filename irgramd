#!/usr/bin/env python3

import logging
import os

import tornado.ioloop
import tornado.options
import tornado.tcpserver

import telethon

# Local modules

from irc import *


# IRC Telegram Daemon

class IRCTelegramd(tornado.tcpserver.TCPServer):
    def __init__(self, address=None, port=6667, config_dir=None, **settings):
        tornado.tcpserver.TCPServer.__init__(self)

        self.logger     = logging.getLogger()
        self.address    = address or '127.0.0.1'
        self.port       = port
        self.config_dir = config_dir or os.path.expanduser('~/.config/irtelegramd')

        if not os.path.exists(self.config_dir):
            os.makedirs(self.config_dir)

    async def handle_stream(self, stream, address):
        handler = IRCHandler(stream, address, self.config_dir)
        await handler.run()

    def run(self):
        self.listen(self.port, self.address)
        self.logger.info('IRTelegramd listening on %s:%s', self.address, self.port)
        self.logger.info('Configuration Directory: %s', self.config_dir)

        tornado.ioloop.IOLoop.current().start()


# Main Execution

if __name__ == '__main__':
    tornado.options.define('address', default=None, help='Address to listen on.')
    tornado.options.define('port', default=6667, help='Port to listen on.')
    tornado.options.define('config_dir', default=None, help='Configuration directory')
    tornado.options.parse_command_line()

    options    = tornado.options.options.as_dict()
    irc_server = IRCTelegramd(**options)
    irc_server.run()
