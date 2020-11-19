
import itertools

# Utilities

def chunks(iterable, n, fillvalue=None):
    ''' Return iterable consisting of a sequence of n-length chunks '''
    args = [iter(iterable)] * n
    return itertools.zip_longest(*args, fillvalue=fillvalue)
