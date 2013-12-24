#!/usr/bin/env python
import sys, subprocess
from os import chdir
from os.path import dirname, join
import utils


def rsync_upload(pages, dest, extra_rsync_args = [], delete = True):
  with utils.pushd(pages):
    sys.stderr.write("Uploading {} to {}...\n".format(pages, dest))
    subprocess.check_call(['rsync',
      '-a', '-v', '--progress'
      ] + (['--delete'] if delete else []) + extra_rsync_args + [
      '.',
      dest
      ])
    sys.stderr.write("Done uploading {} to {}.\n".format(pages, dest))

def s3up(resources_dir, s3dest):
  """
  resources_dir: a directory with gz/ and nogz/ subdirectories to be uploaded
                 whose files have mime-types that can be easily guessed,
                 and a file cdn.robots.txt to be uploaded as the S3 bucket's
                 robots.txt.
  s3dest: s3://bucket-name

  Requires 's3cmd' to be installed ( http://s3tools.org/s3cmd ).
  """
  print("""Warning: s3up may not be up to date with my preferred HTTP headers,
and Amazon S3 didn't even allow specifying some of my chosen headers.
""")

  with utils.pushd(resources_dir):
    sys.stderr.write("Uploading to Amazon S3...\n")
    # Make robots revalidate robots.txt every fifteen seconds
    # (if they're smart enough to).
    # That way, if I change my mind about what it is,
    # the robots (in theory!) will obey fairly promptly.
    subprocess.check_call(['s3cmd', 'put', '--no-preserve',
      "--add-header='Cache-Control: max-age=15, must-revalidate'",
      'cdn.robots.txt', s3dest+'/robots.txt'])
    flags = [
      '--skip-existing', '--no-delete-removed', '--no-preserve',
      "--add-header='Cache-Control: max-age=8000000'" ]
    subprocess.check_call(['s3cmd'] + flags + ['sync', 'nogz', s3dest])
    subprocess.check_call(['s3cmd'] + flags + [
      "--add-header='Content-Encoding: gzip'", 'sync', 'gz', s3dest])
    sys.stderr.write("Done uploading to Amazon S3.\n")



