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


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def check_directory(directory):
    if not os.access(directory, os.W_OK | os.X_OK):
        raise argparse.ArgumentTypeError(
            '{} is not a writable directory'.format(directory)
        )
    return directory

def parse_args():
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
        type=check_directory,
        default=os.getcwd()
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
    Source: http://stackoverflow.com/questions/377017/test-if-executable-exists-in-python/377028#377028
    '''
    def is_exe(fpath):
        return os.path.isfile(fpath) and os.access(fpath, os.X_OK)

    fpath, fname = os.path.split(program)
    if fpath:
        if is_exe(program):
            return program
    else:
        for path in os.environ["PATH"].split(os.pathsep):
            path = path.strip('"')
            exe_file = os.path.join(path, program)
            if is_exe(exe_file):
                return exe_file
    return None


class TimeoutError(Exception):
    pass


def timeout(seconds=10, error_message=os.strerror(errno.ETIME)):
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
    logger.info('Restore original config file')
    shutil.move('{}.bak'.format(config.name, '.bak'), config.name)


def backup_config(config):
    logger.info('Back up config file')
    shutil.copy2(config.name, '{}.bak'.format(config.name, '.bak'))


def update_config(config, remote, rclone_local_dir):
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
    for d in directories:
        if not os.path.exists(d):
            logging.info('Create directory {}'.format(d))
            os.makedirs(d)


def umount_dirs(directories):
    for d in directories:
        fusermount_bin = which('fusermount')
        if os.path.ismount(d):
            umount_cmd = '{} -u {}'.format(fusermount_bin, d)
            logging.info('Call {}'.format(umount_cmd))
            try:
                subprocess.call(shlex.split(umount_cmd))
            except Exception as e:
                logger.error(e)


def remove_dirs(directories):
    for d in directories:
        if os.path.exists(d):
            logging.info('Remove directory {}'.format(d))
            shutil.rmtree(d)


def copy_files(files, destination):
    for f in files:
        if type(f) in [str, unicode]:
            filename = f
        else:
            filename = f.name
        logger.info('Copy {} to {}'.format(filename, destination))
        shutil.copy2(filename, destination)


def rclone_mount(config, rclone_decrypt_dir):
    cmd = '{} --config {} mount local-crypt:/ {}'.format(
        which('rclone'), config.name, rclone_decrypt_dir
    )
    logging.info('Spawn {}'.format(cmd))
    scmd = shlex.split(cmd)
    return subprocess.Popen(scmd)


@timeout(10)
def wait_for_decryption(rclone_decrypt_dir):
    while True:
        print(os.listdir(rclone_decrypt_dir))
        if os.listdir(rclone_decrypt_dir):
            break
        time.sleep(1)
    logging.info('Files were decrypted')


def terminate(rclone_pid, rclone_dirs):
    logging.info('Kill rclone pid {}'.format(rclone_pid))
    os.kill(rclone_pid, signal.SIGTERM)
    umount_dirs(rclone_dirs)
    remove_dirs(rclone_dirs)


def main():
    rclone_local_dir = os.path.expanduser('~/.cache/rclone/local')
    rclone_decrypt_dir = os.path.expanduser('~/.cache/rclone/decrypted')
    rclone_dirs = [rclone_local_dir, rclone_decrypt_dir]
    args = parse_args()

    update_config(args.config, args.remote, rclone_local_dir)
    create_dirs(rclone_dirs)
    copy_files(args.FILES, rclone_local_dir)
    pid = rclone_mount(args.config, rclone_decrypt_dir).pid
    logging.info('rclone pid: {}'.format(pid))
    atexit.register(functools.partial(terminate, pid))
    atexit.register(functools.partial(remove_dirs, rclone_dirs))
    wait_for_decryption(rclone_decrypt_dir)
    copy_files(
        [os.path.join(rclone_decrypt_dir, x) for x in os.listdir(rclone_decrypt_dir)],
        args.destination
    )


if __name__ == '__main__':
    main()
