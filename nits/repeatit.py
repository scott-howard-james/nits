#! python
'''
Description:
    Run the same command on a bunch of files

Usage:
    repeatit -c <command> <files>... [-d]

Text replacement options within (-c) command string:
    - %f gets replaced with the file name
    - %n gets replaced with the file name up to the last extension

Options:
    -h --help                show this screen
    -c, --command <command>  command
    -f, --files <files>      file list
    -d, --dontwait           do not wait for them to complete

Example(s):
    Print names of text files:

    `repeatit -c "echo %f" *.txt`

    Unzip files in subfolders in place:

    `repeatit -c "cd %f;unzip *.zip" *`

'''

#internal
import subprocess
# external
from docopt import docopt

def process():
    doing = {}
    args = docopt(__doc__)
    for file in args['<files>']:
        doing = subprocess.Popen(
            args['--command'].replace(
                '%f', file).replace(
                '%n', '.'.join(file.split('.')[:-1])
                ),
            shell=True)

    if not args['--dontwait']:
        for file in args['<files>']:
            doing.wait()

if __name__ == '__main__':
    process()
