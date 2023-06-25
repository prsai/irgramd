# irgramd: IRC-Telegram gateway
# utils.py: Helper functions
#
# Copyright (c) 2019 Peter Bui <pbui@bx612.space>
# Copyright (c) 2020-2023 E. Bosch <presidev@AT@gmail.com>
#
# Use of this source code is governed by a MIT style license that
# can be found in the LICENSE file included in this project.

import itertools
import textwrap
import re
import datetime
import zoneinfo
import difflib

# Constants

FILENAME_INVALID_CHARS = re.compile('[/{}<>()"\'\\|&]')
SIMPLE_URL = re.compile('http(|s)://[^ ]+')

# Utilities

class command:
    async def parse_command(self, line, nick):
        command = line.partition(' ')[0].lower()
        self.tmp_ircnick = nick
        if command in self.commands.keys():
            handler, min_args, max_args, maxsplit = self.commands[command]
            words = line.split(maxsplit=maxsplit)[1:]
            num_words = len(words)
            if num_words < min_args or num_words > max_args:
                reply = ('Wrong number of arguments',)
            else:
                reply = await handler(*words)
        else:
            reply = ('Unknown command',)

        return reply

class HELP:
    desc = 1
    brief = 2

def chunks(iterable, n, fillvalue=None):
    ''' Return iterable consisting of a sequence of n-length chunks '''
    args = [iter(iterable)] * n
    return itertools.zip_longest(*args, fillvalue=fillvalue)

def set_replace(set, item, new_item):
    if item in set:
        set.remove(item)
        set.add(new_item)

def get_continued(items, mark, length):
    # Add "continued" mark to lines, except last one
    return (x + mark if n != length else x for n, x in enumerate(items, start=1))

def split_lines(message):
    MAX = 400
    messages_limited = []
    wr = textwrap.TextWrapper(width=MAX)

    # Split when Telegram original message has breaks
    messages = message.splitlines()
    lm = len(messages)
    if lm > 1:
        # Add "continued line" mark (\) for lines that belong to the same message
        # (split previously)
        messages = get_continued(messages, ' \\', lm)
    for m in messages:
        wrapped = wr.wrap(text=m)
        lw = len(wrapped)
        if lw > 1:
            # Add double "continued line" mark (\\) for lines that belong to the same message
            # and have been wrapped to not exceed IRC limits
            messages_limited += get_continued(wrapped, ' \\\\', lw)
        else:
            messages_limited += wrapped
    del wr
    return messages_limited

def sanitize_filename(fn):
    return FILENAME_INVALID_CHARS.sub('', fn).strip('-').replace(' ','_')

def remove_slash(url):
    return url[:-1] if url[-1:] == '/' else url

def remove_http_s(url):
    if url[:8] == 'https://':
        surl = url[8:]
    elif url[:7] == 'http://':
        surl = url[7:]
    else:
        surl = url
    return remove_slash(surl)

def is_url_equiv(url1, url2):
    if url1 and url2:
        return url1 == url2 or remove_slash(remove_http_s(url1)) == remove_slash(remove_http_s(url2))
    else:
        return False

def extract_url(text):
    url = SIMPLE_URL.search(text)
    return url.group() if url else None

def get_human_size(size):
    human_units = ('', 'K', 'M', 'G', 'T', 'P', 'E', 'Z', 'Y')

    def get_human_size_values(size, unit_pos=0):
        aux = size / 1024.0
        if aux > 1: return get_human_size_values(aux, unit_pos + 1)
        else: return size, human_units[unit_pos]

    if size <= 1237940039285380274899124224:    # 1024Y
        num, unit = get_human_size_values(size)
    else:
        num = size / 1208925819614629174706176  # 1Y
        unit = 'Y'

    fs = '{:.1f}{}' if num < 10 else '{:.0f}{}'

    return fs.format(num, unit)

def get_human_duration(duration):
    res = ''
    x, s = divmod(duration, 60)
    h, m = divmod(x, 60)

    if h > 0: res = str(h) + 'h'
    if m > 0: res += str(m) + 'm'
    if s > 0: res += str(s) + 's'
    return res

def compact_date(date, tz):
    delta = datetime.datetime.now(datetime.timezone.utc) - date
    date_local = date.astimezone(zoneinfo.ZoneInfo(tz))

    if delta.days < 1:
        compact_date = date_local.strftime('%H:%M')
    elif delta.days < 365:
        compact_date = date_local.strftime('%d-%b')
    else:
        compact_date = date_local.strftime('%Y')

    return compact_date

def get_highlighted(a, b):
    awl = len(a.split())
    bwl = len(b.split())
    delta_size = abs(awl - bwl)
    highlighted = True

    if not a:
        res = '> {}'.format(b)
    elif delta_size > 5:
        res = b
        highlighted = False
    else:
        al = a.split(' ')
        bl = b.split(' ')
        diff = difflib.ndiff(al, bl)
        ld = list(diff)
        res = ''
        d = ''
        eq = 0

        for i in ld:
            if i == '- ' or i[0] == '?':
                continue
            elif i == '  ' or i == '+ ':
                res += ' '
                continue
            # deletion of words
            elif i[0] == '-':
                res += '-{}- '.format(i[2:])
            # addition of words
            elif i[0] == '+':
                res += '_{}_ '.format(i[2:])
            else:
                res += '{} '.format(i[2:])
                eq += 1

        delta_eq = bwl - eq
        if delta_eq > 3:
            res = b
            highlighted = False

    return res, highlighted

def fix_braces(text):
    # Remove braces not closed, if the text was truncated
    if text.endswith(' {...'):
        subtext = text[:-5]
        if not '{}' in subtext:
            return '{}...'.format(subtext)
    return text

def format_timestamp(format, tz, date):
    date_local = date.astimezone(zoneinfo.ZoneInfo(tz))
    return date_local.strftime(format)
