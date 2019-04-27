'''
Description:
   A simple timestamping logging class
'''
# standard
import logging
import sys

class TimeStamp(logging.Formatter):

    def __init__(self):
        super(TimeStamp, self).__init__(
            '[%(asctime)s] %(levelname)s:%(message)s', '%Y/%m/%d %H:%M:%S')

    def format(self, record):
        return ''.join(super(TimeStamp, self).format(record).split('INFO:')) # delete 'INFO

class Reporter(logging.Logger):
    '''
    A simple timestamping logging class
    '''

    def __init__(self, name=None, verbose=False):
        logging.Logger.__init__(self, name=name)
        screen = logging.StreamHandler(sys.stdout)
        screen.setFormatter(TimeStamp())
        self.addHandler(screen)
        if verbose:
            self.setLevel(logging.INFO)
        else:
            self.setLevel(logging.WARN)

    def _target(self, message, target):
        return message + ('' if target is None else '[' + str(target) + ']')

    def say(self, message, target=None):
        '''
        report message
        '''
        self.info(self._target(message, target))

    def warn(self, message, target=None):
        '''
        report warning
        '''
        self.warning(self._target(message, target))

    def abort(self, message, target=None):
        '''
        report error and exit
        '''
        message = self._target(message, target)
        self.error(message)
        sys.exit(-1)
