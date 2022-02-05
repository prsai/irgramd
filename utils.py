
import itertools
import textwrap
import re

# Utilities

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
