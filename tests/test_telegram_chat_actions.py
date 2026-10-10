# irgramd: IRC-Telegram gateway
# Use of this source code is governed by the MIT style license in LICENSE.

import datetime
import unittest
from unittest.mock import AsyncMock, Mock

from telethon import events, types

from telegram import TelegramHandler


class ChatActionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.handler = TelegramHandler.__new__(TelegramHandler)
        self.handler.logger = Mock()
        self.handler.get_peer_id_and_type = Mock(
            side_effect=[(100, 'chan'), (200, 'user')]
        )
        self.handler.get_irc_user_from_telegram = Mock(return_value='user')
        self.handler.get_irc_channel_from_telegram_id = Mock(return_value='#channel')
        self.handler.telegram_client = Mock(get_entity=AsyncMock())
        self.handler.irc = Mock(
            join_irc_channel=AsyncMock(), part_irc_channel=AsyncMock()
        )

    async def test_unpin_without_service_message(self):
        updates = [
            types.UpdatePinnedChannelMessages(
                channel_id=100, messages=[123], pts=1, pts_count=0, pinned=False
            ),
            types.UpdatePinnedMessages(
                peer=types.PeerChat(100), messages=[123],
                pts=1, pts_count=0, pinned=False,
            ),
        ]
        for update in updates:
            with self.subTest(update=type(update).__name__):
                event = events.ChatAction.build(update)
                self.assertTrue(event.unpin)
                self.assertIsNone(event.action_message)
                await self.handler.handle_telegram_chat_action(event)

        self.handler.get_peer_id_and_type.assert_not_called()
        self.handler.telegram_client.get_entity.assert_not_awaited()
        self.handler.irc.join_irc_channel.assert_not_awaited()
        self.handler.irc.part_irc_channel.assert_not_awaited()

    async def test_service_message_membership_actions(self):
        message = types.MessageService(
            id=123, peer_id=types.PeerChannel(100), from_id=types.PeerUser(200),
            date=datetime.datetime.now(datetime.timezone.utc),
            action=types.MessageActionChatAddUser(users=[200]),
        )
        for flags, operation in [
            ({'added_by': True}, 'join'),
            ({'added_by': 300}, 'join'),
            ({'kicked_by': True}, 'part'),
            ({'kicked_by': 300}, 'part'),
        ]:
            with self.subTest(flags=flags):
                self.setUp()
                event = events.ChatAction.Event(message, users=[200], **flags)
                await self.handler.handle_telegram_chat_action(event)
                if operation == 'join':
                    self.handler.irc.join_irc_channel.assert_awaited_once_with(
                        'user', '#channel', irc_join=False
                    )
                    self.handler.irc.part_irc_channel.assert_not_awaited()
                else:
                    self.handler.irc.part_irc_channel.assert_awaited_once_with(
                        'user', '#channel'
                    )
                    self.handler.irc.join_irc_channel.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
