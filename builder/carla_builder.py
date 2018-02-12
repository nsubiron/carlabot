#!/usr/bin/env python3

import argparse
import datetime
import humanfriendly
import json
import logging
import os
import re
import shutil
import subprocess
import yaml

DRY_RUN = False

GIT_INFO = ['git', 'log', '--format="`%h` _"%s"_ by *%an*"', '-n 1']
GIT_TAG = ['git', 'describe', '--tags', '--dirty', '--always']


def print_out(text):
    print(text)
    logging.info(re.sub(r"\:[\S]+\:", '', str(text)).strip())


class Time(object):
    def __init__(self, seconds=0):
        self.seconds = seconds

    def __add__(self, rhs):
        return Time(self.seconds + rhs.seconds)

    def __str__(self):
        return humanfriendly.format_timespan(self.seconds)


class StopWatch(object):
    def __init__(self):
        self.start = datetime.datetime.now()
        self.end = None

    def stop(self):
        self.end = datetime.datetime.now()

    @property
    def elapsed_time(self):
        end = datetime.datetime.now() if self.end is None else self.end
        return Time((end - self.start).total_seconds())


class BuildStep(object):
    def __init__(self, command, working_dir, description='No description'):
        self.command = command if isinstance(command, list) else str(command).split(' ')
        self.description = description
        self.working_dir = working_dir
        self.exception = None
        self.stdout = None
        self.stderr = None
        self.errcode = None
        self.success = False
        self.elapsed_time = Time()

    def run(self):
        stop_watch = StopWatch()
        try:
            self.stdout, self.stderr, self.errcode = popen(self.command, self.working_dir)
            logging.info(
                '"{description}" finished with code {errcode}\n'
                '- - - stdout\n{stdout}\n'
                '- - - stderr\n{stderr}\n- - -'.format(**vars(self)))
        except Exception as exception:
            self.exception = exception
        self.elapsed_time = stop_watch.elapsed_time
        self.success = self.errcode == 0
        return self.success

    def __str__(self):
        mark = ':white_check_mark:' if self.success else ':x:'
        return ' '.join([mark, self.description, '({0})'.format(self.elapsed_time)])

    def error_message(self):
        if self.exception is not None:
            msg = '\n"{description}" failed with exception:\n```\n{exception}\n```'
        elif self.errcode != 0:
            msg = '\n"{description}" failed with error {errcode:d}:\n```\n{stdout}\n{stderr}\n```'
        return msg.format(**vars(self))


def popen(cmd, working_dir):
    kwargs = {'cwd': working_dir, 'shell': False}
    kwargs['stdout'] = subprocess.PIPE
    kwargs['stderr'] = subprocess.PIPE
    # Launch process.
    logging.debug('popen: %s', ' '.join(cmd))
    if DRY_RUN:
        return '', '', 0
    else:
        process = subprocess.Popen(cmd, **kwargs)
        out, err = process.communicate(timeout=None)
        decode = lambda x: None if x is None else x.decode('utf-8')
        return decode(out), decode(err), process.returncode


def mkdir_p(path):
    if not os.path.isdir(path):
        os.makedirs(path)

def rm(path):
    if os.path.isdir(path):
        logging.debug('rm -R %r', path)
        if not DRY_RUN:
            shutil.rmtree(path)
    if os.path.isfile(path):
        logging.debug('rm %r', path)
        if not DRY_RUN:
            os.remove(path)


def do_clean_up(folder, number_of_builds):
    if number_of_builds is None:
        return
    number_of_builds = int(number_of_builds)
    if number_of_builds < 0:
        return
    logging.debug('cleaning up output folder')
    versions = sorted(x for x in os.listdir(folder) if x.endswith('.json'))
    versions = versions[:(len(versions) - number_of_builds)]
    if not versions:
        return
    for filename in versions:
        path = os.path.join(folder, filename)
        with open(path, 'r') as fp:
            data = json.load(fp)
        rm(data['log'])
        if 'release_path' in data:
            rm(data['release_path'])
        rm(path)


def do_the_thing(args):
    try:
        do_clean_up(args.output_dir, args.number_of_builds_to_keep)

        commands = [BuildStep(**arguments) for arguments in args.build]
        logging.debug('running %d steps.', len(commands))

        # Run installation first to get git info.
        if commands[0].run():
            git_info = BuildStep(GIT_INFO, args.install_dir)
            if not git_info.run():
                raise RuntimeError('failed to get git info')
            msg = '\nBuild branch `{0}` at {1}'
            print_out(msg.format(args.branch, git_info.stdout.strip()[1:-1]))
            git_tag = BuildStep(GIT_TAG, args.install_dir)
            if not git_tag.run():
                raise RuntimeError('failed to get git tag')
            args.tag = git_tag.stdout.strip()
            logging.debug('git tag = %r', args.tag)

        print_out('')
        success = True
        total_time = Time()
        for command in commands:
            if success and command.errcode is None:
                success = command.run()
            print_out(command)
            total_time += command.elapsed_time

        print_out('\nBuild finished in %s.' % total_time)

        for command in commands:
            if not command.success:
                print_out(command.error_message())
                print_out('\nBuild failed :disappointed:')
                return

        release_name = 'CARLA_%s.tar.gz' % args.tag
        release_path = os.path.join(args.install_dir, 'Dist', release_name)
        if not os.path.isfile(release_path):
            print_out(':x: Cannot find release package :dizzy_face:')
            return
        release_dest = os.path.join(args.output_dir, release_name)
        shutil.move(release_path, release_dest)
        args.release = release_name
        args.release_path = release_dest

        args.success = True
        print_out('\nGreat! everything works :slightly_smiling_face:')

        if args.download_prefix is not None:
            args.release_link = args.download_prefix + release_name
            print_out('\nYou can download your build from %s' % args.release_link)

    finally:
        filename = os.path.join(args.output_dir, '%s.json' % args.timestamp)
        with open(filename, 'w+') as fp:
            fp.write(json.dumps(vars(args), indent=2))
        if not args.keep_intermediate:
            rm(args.install_dir)


def main():
    argparser = argparse.ArgumentParser(description=__doc__)
    argparser.add_argument(
        '-n', '--dry-run',
        action='store_true',
        help='perform a trial run')
    argparser.add_argument(
        '-b', '--branch',
        metavar='B',
        default='master',
        help='branch or tag to build')
    argparser.add_argument(
        '--keep-intermediate',
        action='store_true',
        help='keep intermediate files and folders')

    args = argparser.parse_args()

    if args.dry_run:
        global DRY_RUN
        DRY_RUN = True

    this_script_folder = os.path.dirname(os.path.realpath(__file__))

    with open(os.path.join(this_script_folder, 'config.yaml'), 'r') as fp:
        config = yaml.load(fp)

    getpath = lambda x: os.path.realpath(os.path.join(this_script_folder, x))

    args.success = False
    args.repo = config['repo']
    args.timestamp = '{:%Y%m%d%H%M%S}'.format(datetime.datetime.now())
    args.build_dir = getpath(config.get('build_dir', '../_intermediate'))
    args.install_dir = os.path.join(args.build_dir, args.timestamp)
    args.output_dir = getpath(config.get('output_dir', '../_builds'))
    args.log = os.path.join(args.output_dir, '%s.log' % args.timestamp)
    args.number_of_builds_to_keep = config.get('number_of_builds_to_keep', None)
    args.download_prefix = config.get('download_prefix', None)

    parse = lambda x: dict((k, v.format(**vars(args))) for k, v in x.items())
    args.build = [parse(step) for step in config['build']]

    mkdir_p(args.build_dir)
    mkdir_p(args.install_dir)
    mkdir_p(args.output_dir)

    logging_config = {
        'format': '%(levelname)s: %(message)s',
        'level': logging.DEBUG,
        'filename': args.log,
        'filemode': 'w+'
    }
    logging.basicConfig(**logging_config)

    do_the_thing(args)


if __name__ == '__main__':

    try:
        main()
    except KeyboardInterrupt:
        print_out('\nCancelled by user. Bye!')
