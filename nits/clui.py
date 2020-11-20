'''
Description:
    Command Line User Interface (CLUI)

Dependencies:
- docopt
- nits

'''
# standard
# external
import docopt
from nits.reporter import Reporter
# internal

class CLUI:

    def __init__(self, docopt_header):
        args = self.args = docopt.docopt(docopt_header)
        self.reporter = Reporter(verbose=args['--verbose'])
        self.say, self.abort, self.warn = self.reporter.say, self.reporter.abort, self.reporter.warn

    def cast(self, f, fields, separator=None):
        '''
        Docopt does not support argument typing; support it.
        Change the values of the arguments directly.
        '''
        for field in fields:
            value = self.args[field]
            self.args[field] =  f(value) if separator is None else [f(x) for x in value.split(separator)]

    def __getitem__(self, key):
        return self.args[key]

    def __str__(self):
        return str(self.args)
