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
    def total_seconds(td): # standard in 2.7
        return (td.microseconds + (
            td.seconds + td.days * 24 * 3600) * 10.**6) / 10**6
    return total_seconds(d - EPOCH)

unix2date = datetime.utcfromtimestamp

def now2unix():
    return date2unix(datetime.utcnow())

def now2time():
    return datetime.now()

def now2str(format=DEFAULT_DATETIME_STAMP):
    return datetime.now().strftime(format)

def str2unix(s, format=DEFAULT_DATETIME_STAMP): # string -> unix seconds
    return date2unix(datetime.strptime(s,format))

def unix2str(u, format=DEFAULT_DATETIME_STAMP, zone_offset=0): # unix seconds -> string
    u = u + (zone_offset * 3600)
    return datetime.strftime(unix2date(u), format)

def time2date(t):
    return datetime.combine(datetime.today(), t)

def file2time(f):
    return os.stat(f).st_mtime

def time2file(f, time):
    os.utime(f, (time, time))

class Test_Time(unittest.TestCase):

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
