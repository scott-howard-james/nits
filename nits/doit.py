#! python
'''
Description:
   Run another program from this folder

Notes:
    - All parameters are passed on to the <command>
    - Use DOIT_FOLDER environment variable to change program folder

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
    'sh':'sh'
}

def files(folders):
    for folder in folders:
        for filename in Path(folder).iterdir():
            if filename.is_file() and str(filename).split('.')[-1] in EXECUTABLES:
                yield filename

def show(folders):
    PROGRAM_NAME_LENGTH = 20 # ToDo: calculate this dynamically

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
    if 'DOIT_FOLDER' in os.environ:
        folders = os.environ['DOIT_FOLDER'].split(':')
    else:
        folders = ['/'.join(os.path.realpath(__file__).split('/')[:-1])]

    if len(sys.argv) < 2:
        show(folders)
    else:
        command = find(sys.argv[1], folders)
        if command is None:
            show(folders)
        else:
            subprocess.Popen([EXECUTABLES[command.split('.')[-1]]] + [command] + sys.argv[2:]).wait()

if __name__ == '__main__':
    process()
