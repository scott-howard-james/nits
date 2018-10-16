# standard
from collections import defaultdict, OrderedDict
import csv
import sys
import tempfile
import unittest

class File:
    '''
    An abstract class simplifying file access through the use of only two functions:

    - read (file)
    - write (data, file):
    '''
    @classmethod
    def read(cls, filename):
        '''
        return file elements in a generator
        '''
        assert False

    @classmethod
    def write(cls, data, filename):
        '''
        write data to filename
        '''
        assert False

class Text(File):
    '''
    Instantiate the File class for a simple text file
    '''
    @classmethod
    def read(cls, filename, comment=None, blanklines=False, strip=True):
        '''
        - comment: ignore comments
        - blanklines: ignore blank lines
        - strip: strip write space
        '''
        def line(d):
            if comment is None:
                return d
            elif comment not in d:
                return d
            else:
                return d[:d.index(comment)].strip()

        with open(filename, 'rt') as f:
            for datum in f:
                if strip:
                    d = datum.strip()
                else:
                    d = datum.rstrip()
                if blanklines:
                    yield line(d)
                elif len(d) > 0:
                    remnant = line(d)
                    if len(remnant) > 0:
                        yield remnant

    @classmethod
    def write(cls,
        data,
        filename,
        eol='\n' # explicitly change the End of Line marker
        ):
        if filename is None:
            f = sys.stdout
        else:
            f = open(filename, 'wt')
        with f:
            for datum in data:
                f.write(datum + eol)

class CSV(File):
    '''
    Instantiate the File class for Comma Separated Values (CSV)
    '''
    @classmethod
    def read(cls,
        filename,
        header=True,
        fields=None):
        '''
        - header: is first line the header?
        - fields: optional list of field values
        '''
        with open(filename, 'rt') as file:
            csv_file = csv.reader(file)
            for i, record in enumerate(csv_file):
                if len(record) == 0:
                    continue
                record = [f.strip() for f in record]
                if header:
                    if i == 0:
                        if fields is None:
                            fields = record
                    else:
                        yield OrderedDict(list(zip(fields, record)))
                else:
                    yield record

    @classmethod
    def write(cls,
        data,
        filename=None,
        fields=None,
        header=True,
        append=False,
        delimiter=','):
        '''
        - fields: optional list of field values
        - header: display header on first line?
        - append: add to existing file?
        - delimiter: what character to use for separating elements
        '''

        def formatter(datum, fields):
            if not isinstance(datum, dict):
                return dict(list(zip(fields, [str(d) for d in datum])))
            else:
                d = defaultdict()
                for field in fields:
                    if field in datum:
                        d[field] = datum[field]
                return d
        if append:
            mode = 'a'
        else:
            mode = 'w'

        if filename is None:
            f = sys.stdout
        elif sys.version_info < (3, 0, 0):
            mode += 'b'
            f = open(filename, mode)
        else:
            f = open(filename, mode, newline='')

        with f as csv_file:
            first = True
            for datum in data:
                if first:
                    if fields is None:
                        if isinstance(datum, dict):
                            fields = list(datum.keys())
                        else:
                            fields = datum  # first line is the list of fields
                    csv_writer = csv.DictWriter(csv_file, fields,
                        lineterminator='\n', delimiter=delimiter)
                    if header:
                        csv_writer.writerow(dict(list(zip(fields, fields))))
                    first = False
                csv_writer.writerow(formatter(datum, fields))

class Test_File(unittest.TestCase):

    def setUp(self):
        self.named = tempfile.NamedTemporaryFile(delete=True)
        self.data = [[i+str(j) for j in range(4)] for i in ['x', 'a', 'b', 'c']]
        self.filename = self.named.name

    def tearDown(self):
        self.named.close()

    def test_text(self):
        data = [' '.join(datum) for datum in self.data]
        Text.write(data, self.filename)
        for i, same in enumerate(Text.read(self.filename)):
            assert data[i] == same

    def test_csv(self):
        CSV.write(self.data, self.filename, header=False)
        for i, same in enumerate(CSV.read(self.filename, header=True)):
            assert list(same.keys()) == self.data[0]
            assert list(same.values()) == self.data[i+1]

if __name__ == '__main__':
    unittest.main()
