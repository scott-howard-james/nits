# standard
import math
import re
import unittest

class Cast:
    '''
    Factory for creating "casts" (https://en.wikipedia.org/wiki/Type_conversion), that is, functions which:

    1. change a value into another with the same semantic content but (perhaps) a different type
    2. return a default value in the case of no parameters

    Notes:

    - The intention of Cast is to provide a general capability similar to python typers such str() and int().
    - It is assumed that casts reapplied to their own results are the identity function
    '''
    def __init__(self, cast, default=None, compare=0):
        '''
        initializion

        - stores the casting function
        - creates an initial default value for the factory
        - performs a basic compare (1-cycle identity)
        '''
        self.caster = cast
        self.defaulter = default
        assert cast(compare) == cast(cast(compare))

    def cast(self, default=None):
        '''
        creates the casting function.  The class default may be overwritten here.
        '''
        def convert(thing=None):
            if thing is not None:
                return self.caster(thing)
            elif default is not None:
                return self.caster(default)
            elif self.defaulter is not None:
                return self.caster(self.defaulter)
            elif self.defaulter is None and default is None and thing is None:
                return self.caster()
            else:
                assert False # logic error
        return convert

class Make():
    '''
    A collection of useful conversions
    '''
    @staticmethod
    def identity(x=None):
        return x

    HEXADECIMAL = re.compile('[a-fA-F0-9]{2}') # preserve for speed
    @staticmethod
    def hex_string(x):
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
            assert Make.HEXADECIMAL.match(x)
            return x.upper()
        elif isinstance(x, float) or isinstance(x, int):
            return hexed(int((1 if abs(x) >= 1 else abs(x) % 1)*255))
        else:
            assert False

    @staticmethod
    def sign(x=0):
        return float(x) and (1, -1)[float(x) < 0]

    @staticmethod
    def degree(x=0.0):
        return float(x)%360

    @staticmethod
    def signed_degree(x=0.0):
        y = Make.degree(x)
        return y - 360 if y > 180 else y

    @staticmethod
    def signed_degree_90(x=0):
        y = Make.signed_degree(x)
        return Make.sign(y)*(180 - abs(y)) if abs(y) > 90 else y

    @staticmethod
    def fraction(x=0):
        '''
        number between zero and one
        '''
        if x - x//1 == 0:
            return 1 if x > 0 else 0
        else:
            return x % 1

    @staticmethod
    def numeric(x=0):
        if isinstance(x, str) and not x:
            return 0
        else:
            return float(x)

    @staticmethod
    def integer(x=0):
        return int(Make.numeric(x)) # handle strings representing fractions

    @staticmethod
    def abs_numeric(x=0):
        return abs(Make.numeric(x))

    @staticmethod
    def abs_integer(x=0):
        return abs(Make.integer(x))


    @staticmethod
    def none(f):
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
    A collection of useful casting functions
    '''
    # primitive type classes

    Integer = Cast(Make.integer)
    Numeric = Cast(Make.numeric)
    String = Cast(str)
    Fraction = Cast(Make.fraction)

    # primitive type casts

    integer = Integer.cast()
    numeric = Numeric.cast()
    string = String.cast()

    # allow casts to return None

    none_numeric = Cast(Make.none(Make.numeric)).cast()
    none_integer = Cast(Make.none(Make.integer)).cast()
    none_string = Cast(Make.none(str)).cast()

    abs_numeric = Cast(Make.abs_numeric).cast()
    abs_integer = Cast(Make.abs_integer).cast()

    # more casts

    fraction = Fraction.cast()
    sign = Cast(Make.sign).cast()
    degree = Cast(Make.degree).cast()
    signed_degree = Cast(Make.signed_degree).cast()
    signed_degree_90 = Cast(Make.signed_degree_90).cast()
    hex_string = Cast(Make.hex_string, '00').cast()

class Test_Cast(unittest.TestCase):

    def setUp(self):
        self.unknown = 'Unknown'

    def test_string(self):
        unk = Cast(str).cast(self.unknown)
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
        assert To.integer('2.12') == 2
        assert To.integer() is 0
        assert To.none_integer() is None
        assert To.numeric() == 0.0
        assert To.numeric('') == 0.0
        assert To.none_numeric() is None
        assert To.none_numeric(1.1) == 1.1
        assert To.none_numeric(0) == 0
        assert To.none_string('') is None
        assert To.none_string() is None
        assert To.none_string(' ') == ' '
        assert To.string() == ''
        assert To.string(11) == '11'
        assert To.abs_integer('-1.03') == 1
        assert To.Integer.cast(11)() == 11

    def test_hex_string(self):
        assert To.hex_string(1.) == To.hex_string(1) == To.hex_string('fF') == 'FF'
        assert To.hex_string() == To.hex_string(0) == To.hex_string(0.) == '00'
        for thing in [.1, 1, 'a0']:
            assert To.hex_string(To.hex_string(thing)) == To.hex_string(thing)

    def test_identity(self):
        identity = Cast(lambda x: x).cast(self.unknown)
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
