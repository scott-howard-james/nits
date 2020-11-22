#! python
'''
Description:
   Run another program from this folder

Environment variables:
    - DOITPATH:  assign program folder
    - PYTHON: the python executable name (e.g. python3)

Usage:
    doit [<command>] [<parameter>...]

Example(s):
    `doit something.py else.py -v --folder stuff`
'''

# standard
from pathlib import Path
import os
import subprocess
import sys

EXECUTABLES = {
    'py':'python',
    'sh':'sh',
    'doit': ['/'.join(os.path.realpath(__file__).split('/')[:-1])]
}

def files(folders):
    for folder in folders:
        for filename in Path(folder).iterdir():
            if filename.is_file() and str(filename).split('.')[-1] in EXECUTABLES:
                yield filename

def show(folders):
    PROGRAM_NAME_LENGTH = 20 # ToDo!: calculate this dynamically

    def descriptions(folders):
        yield 'program', 'description'
        yield '-------', '-----------'
        for file in files(folders):
            filename = str(file)
            with open(filename, 'r') as f:
                text = [x.replace('#','').strip().lower() for x in f.readlines()]
                description = text[text.index('description:')+1] if 'description:' in text else ''
                yield filename.split('/')[-1], description

    for left, right in descriptions(folders):
        print(left.ljust(PROGRAM_NAME_LENGTH), right)

def find(code, folders):
    for file in files(folders):
        filename = str(file)
        if code == filename.split('/')[-1][:len(code)]:
            return filename
    return None

def process():
    if 'DOITPATH' in os.environ:
        EXECUTABLES['doit'] = os.environ['DOITPATH'].split(':')
    if 'PYTHON' in os.environ:
        EXECUTABLES['py'] = os.environ['PYTHON']
    if 'SHELL' in os.environ:
        EXECUTABLES['sh'] = os.environ['SHELL']

    if len(sys.argv) < 2:
        show(EXECUTABLES['doit'])
    else:
        command = find(sys.argv[1], EXECUTABLES['doit'])
        if command is None:
            show(EXECUTABLES['doit'])
        else:
            subprocess.Popen([EXECUTABLES[command.split('.')[-1]]] + [command] + sys.argv[2:]).wait()

if __name__ == '__main__':
    process()
