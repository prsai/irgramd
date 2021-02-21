
irc_codes = \
{
  'RPL_WELCOME': ('001', ':Welcome to the irgramd gateway, {}'),
  'RPL_YOURHOST': ('002', ':Your host is {}, running version irgramd-{}'),
  'RPL_CREATED': ('003', ':This server was created {}'),
  'RPL_MYINFO': ('004', '{} irgramd-{} o nt'),
  'RPL_ISUPPORT': ('005', 'CASEMAPPING=ascii CHANLIMIT=#&+: CHANTYPES=&#+ CHANMODES=,,,nt CHANNELLEN={} NICKLEN={} SAFELIST :are supported by this server'),
  'RPL_WHOISUSER': ('311', '{} {} {} * :{}'),
  'RPL_WHOISSERVER': ('312', '{} {} :irgramd gateway'),
  'RPL_WHOISOPERATOR': ('313', '{} :is an irgramd operator'),
  'RPL_ENDOFWHO': ('315', '{} :End of WHO list'),
  'RPL_WHOISIDLE': ('317', '{} {} :seconds idle'),
  'RPL_ENDOFWHOIS': ('318', '{} :End of WHOIS command'),
  'RPL_WHOISCHANNELS': ('319', '{} :{}'),
  'RPL_CREATIONTIME': ('329', '{} {}'),
  'RPL_WHOISACCOUNT': ('330', '{} {} :Telegram name'),
  'RPL_TOPIC': ('332', '{} :{}'),
  'RPL_TOPICWHOTIME': ('333', '{} {} {}'),
  'RPL_WHOISBOT': ('335', '{} :is a Telegram bot'),
  'RPL_VERSION': ('351', 'irgramd-{} {} :IRC to Telegram gateway'),
  'RPL_WHOREPLY': ('352', '{} {} {} {} {} H{} :0 {}'),
  'RPL_NAMREPLY': ('353', '{} {} :{}'),
  'RPL_ENDOFNAMES': ('366', '{} :End of NAME reply'),
  'RPL_MOTDSTART': ('375', ':- {} Message of the day - '),
  'RPL_MOTD': ('372', ':- {}'),
  'RPL_ENDOFMOTD': ('376', 'End of MOTD command'),
  'ERR_NOSUCHNICK': ('401', '{} :Nick not found'),
  'ERR_NOSUCHSERVER': ('402', '{} :Target not found'),
  'ERR_NOSUCHCHANNEL': ('403', '{} :Channel not found'),
  'ERR_CANNOTSENDTOCHAN': ('404', 'Cannot send to channel'),
  'ERR_TOOMANYCHANNELS': ('405', 'Too many channels'),
  'ERR_WASNOSUCHNICK': ('406', 'There was no such nick'),
  'ERR_TOOMANYTARGETS': ('407', 'Too many targets'),
  'ERR_NOORIGIN': ('409', 'No origin present'),
  'ERR_NORECIPIENT': ('411', 'No recipient'),
  'ERR_NOTEXTTOSEND': ('412', 'No text to send'),
  'ERR_NOTOPLEVEL': ('413', 'No top level domain'),
  'ERR_WILDTOPLEVEL': ('414', 'Wild top level domain'),
  'ERR_UNKNOWNCOMMAND': ('421', 'Unknown command'),
  'ERR_NOMOTD': ('422', 'No MOTD'),
  'ERR_NOADMININFO': ('423', 'No admin info'),
  'ERR_FILEERROR': ('424', 'File error'),
  'ERR_NONICKNAMEGIVEN': ('431', 'No nickname given'),
  'ERR_ERRONEUSNICKNAME': ('432', '{} :Erroneus nickname'),
  'ERR_NICKNAMEINUSE': ('433', '{} :Nickname in use'),
  'ERR_NICKCOLLISION': ('436', 'Nickname collision'),
  'ERR_USERNOTINCHANNEL': ('441', 'User not in channel'),
  'ERR_NOTONCHANNEL': ('442', 'Not on channel'),
  'ERR_USERONCHANNEL': ('443', 'User on channel'),
  'ERR_NOLOGIN': ('444', 'No login'),
  'ERR_SUMMONDISABLED': ('445', 'Summon disabled'),
  'ERR_USERSDISABLED': ('446', 'Users disabled'),
  'ERR_NOTREGISTERED': ('451', ':Not registered'),
  'ERR_NEEDMOREPARAMS': ('461', 'Need more params'),
  'ERR_ALREADYREGISTRED': ('462', 'Already registered'),
  'ERR_NOPERMFORHOST': ('463', 'Insufficient permissions for host'),
  'ERR_PASSWDMISMATCH': ('464', 'Password mismatch'),
  'ERR_YOUREBANNEDCREEP': ('465', 'You\'re banned, creep'),
  'ERR_KEYSET': ('467', 'Key set'),
  'ERR_CHANNELISFULL': ('471', 'Channel is full'),
  'ERR_UNKNOWNMODE': ('472', 'Unknown mode'),
  'ERR_INVITEONLYCHAN': ('473', 'Invite only channel'),
  'ERR_BANNEDFROMCHAN': ('474', 'Banned from channel'),
  'ERR_BADCHANNELKEY': ('475', 'Bad channel key'),
  'ERR_NOPRIVILEGES': ('481', 'No privileges'),
  'ERR_CHANOPRIVSNEEDED': ('482', 'Channel +o privileges needed'),
  'ERR_CANTKILLSERVER': ('483', 'Cannot kill server'),
  'ERR_NOOPERHOST': ('491', 'No operator host'),
  'ERR_UMODEUNKNOWNFLAG': ('501', 'User mode unknown flag'),
  'ERR_USERSDONTMATCH': ('502', 'Users don\'t match'),
  'RPL_WHOISSECURE': ('671', '{} :is using a secure {} connection with {}'),
}
