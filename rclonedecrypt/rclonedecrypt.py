#!/usr/bin/env python
# coding: utf-8


from __future__ import unicode_literals
import ConfigParser
import argparse
import atexit
import errno
import functools
import logging
import os
import shlex
import shutil
import signal
import subprocess
import time
import zipfile


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def writable_directory(directory):
    '''
    Argparse helper function that determines wheter a provided arguement is
    a writable directory

    :param directory: Path of the directory to check
    :type directory: str or unicode
    '''
    if not os.path.exists(directory):
        raise argparse.ArgumentTypeError(
            '{}: No such file or directory'.format(directory)
        )
    if not os.access(directory, os.W_OK | os.X_OK):
        raise argparse.ArgumentTypeError(
            '{} is not a writable directory'.format(directory)
        )
    return directory

def parse_args():
    '''
    Parse arguments
    :return: The parsed arguments
    :rtype: argparse.Namespace
    '''
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-r', '--remote',
        help='Name of the remote',
        default='acd-crypt',
        required=False
    )
    parser.add_argument(
        '-c', '--config',
        help='Path to rclone config file',
        default=os.path.expanduser('~/.rclone.conf'),
        type=argparse.FileType('r+')
    )
    parser.add_argument(
        '-d', '--destination',
        help='Destination',
        type=writable_directory,
        default=os.getcwd()
    )
    parser.add_argument(
        '-e', '--extract',
        help='Extract zip files',
        action='store_true',
        default=False
    )
    parser.add_argument(
        'FILES',
        type=argparse.FileType('r'),
        nargs='+'
    )
    # parser.add_argument(
    #     'DEST',
    #     help='Where to extract files to',
    #     nargs='?'
    # )
    return parser.parse_args()


def which(program):
    '''
    Determine the full path to an executable
    Source: http://stackoverflow.com/questions/377017/test-if-executable-exists-in-python/377028#377028

    :param program: Name of the program to get the full path to
    :type program: str or unicode
    :return: Full path to the program
    :rtype: str or unicode
    '''
    def is_exe(fpath):
        return os.path.isfile(fpath) and os.access(fpath, os.X_OK)

    fpath, fname = os.path.split(program)
    if fpath:
        if is_exe(program):
            return program
    else:
        for path in os.environ['PATH'].split(os.pathsep):
            path = path.strip('"')
            exe_file = os.path.join(path, program)
            if is_exe(exe_file):
                return exe_file
    return None


class TimeoutError(Exception):
    pass


def timeout(seconds=10, error_message=os.strerror(errno.ETIME)):
    '''
    Decorator that raises an TimeoutError when the timer ends and the function
    has not ended yet
    Source: http://stackoverflow.com/questions/2281850/timeout-function-if-it-takes-too-long-to-finish/2282656#2282656

    :param seconds: Time the decorated function is alloted to return
    :type seconds: int
    :param error_message: Error Message to display when the timeout is reached
    :type error_message: str or unicode
    :return: The decorated function
    :rtype: function
    '''
    def decorator(func):
        def _handle_timeout(signum, frame):
            raise TimeoutError(error_message)

        def wrapper(*args, **kwargs):
            signal.signal(signal.SIGALRM, _handle_timeout)
            signal.alarm(seconds)
            try:
                result = func(*args, **kwargs)
            finally:
                signal.alarm(0)
            return result

        return functools.wraps(func)(wrapper)

    return decorator


def restore_config(config):
    '''
    Restore the config file ie. restore the backup

    :param config: Config file to restore
    :type config: file
    '''
    logger.info('Restore original config file')
    shutil.move('{}.bak'.format(config.name, '.bak'), config.name)


def backup_config(config):
    '''
    Back up the config file

    :param config: Config file to back up
    :type config: file
    '''
    logger.info('Back up config file')
    shutil.copy2(config.name, '{}.bak'.format(config.name, '.bak'))


def update_config(config, remote, rclone_local_dir):
    '''
    Alter rclone's config file. This adds two temporary remotes to be able to
    decrypt the files.

    :param config: Config file to update
    :type config: file
    :param remote: Name of the crypted remote
    :type remote: str or unicode
    :param rclone_local_dir: Local directory to use for the new remotes
    :type rclone_local_dir: str or unicode
    '''
    backup_config(config)
    atexit.register(functools.partial(restore_config, config))
    c = ConfigParser.ConfigParser()
    c.readfp(config)
    c.add_section('local')
    c.set('local', 'type', 'local')
    c.set('local', 'nounc', '')
    c.add_section('local-crypt')
    c.set('local-crypt', 'type', 'crypt')
    c.set('local-crypt', 'remote', 'local:{}'.format(rclone_local_dir))
    c.set('local-crypt', 'filename_encryption', 'off')
    c.set('local-crypt', 'password', c.get(remote, 'password'))
    c.set('local-crypt', 'password2', c.get(remote, 'password2'))
    c.write(config)
    config.close()


def create_dirs(directories):
    '''
    Create a bunch of directories

    :param directories: The path of the directories to create
    :type directories: list
    '''
    for d in directories:
        if not os.path.exists(d):
            logging.info('Create directory {}'.format(d))
            os.makedirs(d)


def umount_dirs(directories):
    '''
    Unmount a bunch of directories

    :param directories: The directories to unmount
    :type directories: list
    '''
    DEVNULL = open(os.devnull, 'w')
    for d in directories:
        fusermount_bin = which('fusermount')
        # if os.path.ismount(d):
        umount_cmd = '{} -u {}'.format(fusermount_bin, d)
        logging.info('Call {}'.format(umount_cmd))
        try:
            subprocess.call(
                shlex.split(umount_cmd),
                stdout=DEVNULL,
                stderr=DEVNULL
            )
        except Exception as e:
            logger.error(e)


def remove_dirs(directories):
    '''
    Remove a bunch of directories

    :param directories: The directories to remove
    :type directories: list
    '''
    for d in directories:
        if os.path.exists(d):
            logging.info('Remove directory {}'.format(d))
            shutil.rmtree(d)

def copytree(src, dst, symlinks=False, ignore=None):
    '''
    Copy files or directories
    Source: http://stackoverflow.com/a/12514470/1872036

    :param src: Source file or directory
    :type src: str or unicode
    :param dst: Destination directory
    :type dst: str or unicode
    :param symlinks: Whether to copy symlinks
    :type symlinks: bool
    :param ignore: Ignore pattern
    :type ignore: callable
    '''
    for item in os.listdir(src):
        s = os.path.join(src, item)
        d = os.path.join(dst, item)
        if os.path.isdir(s):
            shutil.copytree(s, d, symlinks, ignore)
        else:
            shutil.copy2(s, d)


def copy_files(files, destination):
    '''
    Copy a set of files to a directory

    :param files: The files to copy over
    :type files: list
    :param destination: Path to the destination directory
    :type destination: str or unicode
    '''
    for f in files:
        if type(f) in [str, unicode]:
            filename = f
        else:
            filename = f.name
        logger.info('Copy {} to {}'.format(filename, destination))
        copytree(filename, destination)


def extract_files(files, destination):
    '''
    Extract some zipfiles to a common destination

    :param files: The files to copy over
    :type files: list
    :param destination: Path to the destination directory
    :type destination: str or unicode
    '''
    for f in files:
        if type(f) in [str, unicode]:
            filename = f
        else:
            filename = f.name
        if zipfile.is_zipfile(filename):
            # TODO Avoid name collision
            # dest = os.path.join(destination, os.path.basename(filename))
            # create_dirs([dest])
            z = zipfile.ZipFile(filename)
            z.extractall(destination)
        else:
            logger.error('Not a zipfile: {}. Skip.'.format(filename))


def rclone_mount(config, rclone_decrypt_dir):
    '''
    Mount the temporary remote using rclone mount

    :param config: Config file
    :type config: file
    :param rclone_decrypt_dir: Path where to mount the decrypted files to
    :type rclone_decrypt_dir: str or unicode
    :return: PID of the rclone process
    :rtype: int
    '''
    cmd = '{} --config {} mount local-crypt:/ {}'.format(
        which('rclone'), config.name, rclone_decrypt_dir
    )
    logging.info('Spawn {}'.format(cmd))
    scmd = shlex.split(cmd)
    return subprocess.Popen(scmd).pid


@timeout(10)
def wait_for_decryption(rclone_decrypt_dir):
    '''
    Wait for the decryption to happen (ie. rclone mount)

    :param rclone_decrypt_dir: Where to look for files (rclone mount
    mountpoint)
    :type rclone_decrypt_dir: str or unicode
    '''
    while True:
        if os.listdir(rclone_decrypt_dir):
            break
        time.sleep(1)
    logging.info('Files were decrypted')


def clean_up(rclone_pid, rclone_dirs):
    '''
    Clean up by stopping the rclone mount command, umounting and removing the
    temporary directories

    :param rclone_pid: PID of the rclone process
    :type pid: int
    :param rclone_dirs: Paths to the directories to unmount and delete
    :type rclone_dirs: list
    '''
    logging.info('Kill rclone pid {}'.format(rclone_pid))
    os.kill(rclone_pid, signal.SIGTERM)
    umount_dirs(rclone_dirs)
    remove_dirs(rclone_dirs)


def main():
    '''
    Main function, entry point
    '''
    rclone_local_dir = os.path.expanduser('~/.cache/rclone/local')
    rclone_decrypt_dir = os.path.expanduser('~/.cache/rclone/decrypted')
    rclone_dirs = [rclone_local_dir, rclone_decrypt_dir]
    args = parse_args()

    update_config(args.config, args.remote, rclone_local_dir)
    create_dirs(rclone_dirs)
    if args.extract:
        extract_files(args.FILES, rclone_local_dir)
    else:
        copy_files(args.FILES, rclone_local_dir)
    pid = rclone_mount(args.config, rclone_decrypt_dir)
    logging.info('rclone pid: {}'.format(pid))
    atexit.register(functools.partial(clean_up, pid, rclone_dirs))
    wait_for_decryption(rclone_decrypt_dir)
    copy_files(
        [os.path.join(rclone_decrypt_dir, x) for x in \
            os.listdir(rclone_decrypt_dir)],
        args.destination
    )


if __name__ == '__main__':
    main()
