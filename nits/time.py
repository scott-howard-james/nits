# external
from datetime import datetime
import math
import os
import unittest

'''
Convenience functions and constants to deal with python's eclectic date-time packaging conventions
'''

EPOCH = datetime.utcfromtimestamp(0)
DEFAULT_TIME_STAMP = '%H:%M:%S'
DEFAULT_DATE_STAMP = '%Y%m%d'
DEFAULT_DATETIME_STAMP = DEFAULT_DATE_STAMP + ' ' + DEFAULT_TIME_STAMP

def date2unix(d):
    '''
    convert python datetime to POSIX timestamp
    '''
    def total_seconds(td): # standard in 2.7
        return (td.microseconds + (
            td.seconds + td.days * 24 * 3600) * 10.**6) / 10**6
    return total_seconds(d - EPOCH)

unix2date = datetime.utcfromtimestamp

def now2unix():
    '''
    Current time in UNIX format
    '''
    return date2unix(datetime.utcnow())

def now2time():
    '''
    Current time in datetime format
    '''
    return datetime.now()

def now2str(format=DEFAULT_DATETIME_STAMP):
    '''
    Current time in string format
    '''
    return datetime.now().strftime(format)

def str2unix(s, format=DEFAULT_DATETIME_STAMP): # string -> unix seconds
    '''
    Parse string to UNIX time
    '''
    return date2unix(datetime.strptime(s, format))

def unix2str(u, format=DEFAULT_DATETIME_STAMP, zone_offset=0): # unix seconds -> string
    '''
    Create string from UNIX time
    '''
    u = u + (zone_offset * 3600)
    return datetime.strftime(unix2date(u), format)

def time2date(t):
    return datetime.combine(datetime.today(), t)

def file2time(f):
    '''
    Get last modification time of file
    '''
    return os.stat(f).st_mtime

def time2file(f, time):
    '''
    Stamp modification time on file
    '''
    os.utime(f, (time, time))

class Test_Time(unittest.TestCase):
    '''
    Collection of regression tests for UNIX time handling
    '''

    def test_time(self):
        assert date2unix(EPOCH) == 0
        x = 1.27 * 10**9
        d = unix2date(x)
        assert date2unix(unix2date(x)) == x
        assert unix2date(date2unix(d)) == d
        s = unix2str(x)
        assert str2unix(unix2str(x)) == x
        assert unix2str(str2unix(s)) == s
        x += .03
        assert math.isclose(date2unix(unix2date(x)), x)

if __name__ == '__main__':
    unittest.main()
