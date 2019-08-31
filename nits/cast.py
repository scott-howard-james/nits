# standard
import math
import re
import unittest

# Constants

HEXADECIMAL = re.compile('[a-fA-F0-9]{2}') # preserve for speed

# Functionals

def cast(f, default=None):
    '''
    Return a function which:

    1. changes a value into another with the same semantic content but (perhaps) a different type
    2. returns a default value in the case of no parameters

    Notes:

    - The intention of *a* cast is to provide a general capability similar to python typers such str() and int()
    - The purpose of *the* cast function is to allow reassignment of the default and to provide the identity check
    - It is assumed that casts reapplied to their own results are the identity function
    '''

    def inner(thing=None):
        if thing is not None:
            return f(thing)
        elif default is not None:
            return f(default)
        else:
            return f()

    assert inner(default) == inner(inner(default)) # identity check
    return inner

def none(f):
    '''
    Allow functions to return None
    '''
    def inner(x=None):
        if x is None:
            return None
        elif isinstance(x, str) and not x:
            return None
        else:
            return f(x)
    return inner

class To():
    '''
    A collection of casting functions
    '''

    @staticmethod
    def identity(x=None):
        return x

    @staticmethod
    def integer(x=0):
        return int(To.numeric(x)) # handle strings representing fractions

    string = str

    @staticmethod
    def numeric(x=0):
        if isinstance(x, str) and not x:
            return 0
        else:
            return float(x)

    @staticmethod
    def abs_numeric(x=0):
        return abs(To.numeric(x))

    @staticmethod
    def abs_integer(x=0):
        return abs(To.integer(x))

    @staticmethod
    def sign(x=0):
        return float(x) and (1, -1)[float(x) < 0]

    @staticmethod
    def degree(x=0.0):
        return float(x)%360

    @staticmethod
    def signed_degree(x=0.0):
        y = To.degree(x)
        return y - 360 if y > 180 else y

    @staticmethod
    def signed_degree_90(x=0):
        y = To.signed_degree(x)
        return To.sign(y)*(180 - abs(y)) if abs(y) > 90 else y

    # demonstrate use of decorators

    @staticmethod
    @cast
    def fraction(x=0):
        '''
        number between zero and one
        '''
        x = float(x)
        if x - x//1 == 0:
            return 1 if x > 0 else 0
        else:
            return x % 1

    # example of a decorator

    @staticmethod
    @cast
    def hex_string(x='00'):
        '''
        create a To.hex_string, that is, '00'..'ff'.
        conversion depends on context:

        - str: check it
        - float: map as a fraction [0,1]
        - int: map as 8-bit [0,255]
        '''

        def hexed(i):
            return hex(i).zfill(2).split('x')[-1].zfill(2).upper()

        if isinstance(x, str):
            assert len(x) == 2
            assert HEXADECIMAL.match(x)
            return x.upper()
        elif isinstance(x, float) or isinstance(x, int):
            return hexed(int((1 if abs(x) >= 1 else abs(x) % 1)*255))
        else:
            assert False

class Nones:
    numeric = cast(none(To.numeric))
    integer = cast(none(To.integer))
    string = cast(none(str))

class Test_Cast(unittest.TestCase):

    def setUp(self):
        self.unknown = 'Unknown'

    def test_string(self):
        unk = cast(str, self.unknown)
        assert unk() is self.unknown
        assert unk(11) == '11'

    def test_fraction(self):
        def compare(x, y):
            assert math.isclose(To.fraction(x), y)
        compare(0, 0)
        compare(1, 1)
        compare(100, 1)
        compare(-100, 0)
        compare(.1, .1)
        compare(2.1, .1)
        compare(-1.1, .9)
        compare(-.1, .9)

    def test_primitives(self):
        assert To.integer('2.12') == To.integer('2.12') == 2
        assert To.integer('11') == 11
        assert To.integer() is 0
        assert Nones.integer() is None
        assert To.numeric() == 0.0
        assert To.numeric('') == 0.0
        assert Nones.numeric() is None
        assert Nones.numeric(1.1) == 1.1
        assert Nones.numeric(0) == 0
        assert Nones.string('') is None
        assert Nones.string() is None
        assert Nones.string(' ') == ' '
        assert To.string() == ''
        assert To.string(11) == '11'
        assert To.abs_integer('-1.03') == 1

    def test_hex_string(self):
        assert To.hex_string(1.) == To.hex_string(1) == To.hex_string('fF') == 'FF'
        assert To.hex_string() == To.hex_string(0) == To.hex_string(0.) == '00'
        for thing in [.1, 1, 'a0']:
            assert To.hex_string(To.hex_string(thing)) == To.hex_string(thing)

    def test_identity(self):
        identity = cast(lambda x: x, self.unknown)
        assert identity(11) == 11
        assert identity('hello') == 'hello'
        assert identity() == self.unknown

    def test_degree(self):
        assert To.sign(2.13) == 1
        assert To.sign(-100) == -1
        assert To.sign(0) == 0
        assert To.signed_degree(0) == To.signed_degree_90(0) == 0
        assert To.signed_degree_90(91) == 89
        assert To.signed_degree_90(-1) == To.signed_degree_90(181) == -1
        assert To.signed_degree_90(1) == To.signed_degree_90(-181) == 1
        assert To.signed_degree(180.1) == -179.9
        assert To.degree(181) == 181
        assert To.signed_degree() == 0
        assert To.degree() == 0.0
        assert To.degree(181+360*10) == 181

if __name__ == '__main__':
    unittest.main()
