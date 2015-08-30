
"""
A bad Make-like library which provides the following features:

    * Consistent mtime:
        Files generated through the buildsystem lib will always have
        mtime equal to the max mtime of the source files they depend on.
    * Work reuse:
        Files generated through the buildsystem lib whose dependencies
        (including build-scripts) haven't changed, won't be rebuilt
        unnecessarily.
    * Separate build directory:
        By default, all build products appear in ../<dirname>-builds,
        meaning you don't have to .gitignore the build dir.
        To make it easier to avoid leaving byproducts in the source dir,
        by default it copies the source dir to <build dir>/src, sans
        some editor temp files, RCS directories, etc, and cd's to <build dir>.

See run_basic and run's docstrings for detailed documentation.

Its worst feature is that if, when specifying dependencies for work reuse (do),
you miss a dependency, it can't warn you and unexpected non-recompilations
may happen.  Also, it can't prevent you from writing to Python variables
within work-reuse (do) blocks (even though when the work is actually reused,
those blocks won't be run so the Python variables won't be set).
"""

import itertools
from os import stat, utime, rename, link, mkdir, chdir, makedirs, getcwd, walk, listdir
from os.path import join, abspath, dirname, basename, exists, relpath
from shutil import rmtree, copyfile
import re

from . import utils

# TODO somehow make it work in Python 2 without losing precision
# stat's _ns were only added in Python 3.3
def _mtime(fpath):
  return stat(fpath).st_mtime_ns
def _set_mtime(fpath, mtime_ns):
  utime(fpath, ns=(mtime_ns, mtime_ns))
def _mtime_opt(fpath):
  try: return _mtime(fpath)
  except (FileNotFoundError, NotADirectoryError): return None

def _parent_dirs(fpath):
  while fpath != '' and fpath != dirname(fpath):
    fpath = dirname(fpath)
    yield fpath

class pushd(object):
  def __init__(self, target):
    self.target = target
  def __enter__(self):
    self.source = getcwd()
    chdir(self.target)
  def __exit__(self, type, value, traceback):
    chdir(self.source)

def makedirs_with_mtime(dest, mtime):
  """
  Sets the mtime of all created dirs to 'mtime'
  and keeps the mtime of the parent of the top created dir
  unchanged.
  """
  dirs = []
  p = join('.', dest)
  while True:
    if exists(p): break
    dirs.append(p)
    p = dirname(p)
  if len(dirs) == 0: return  #skip mtime shuffling
  p_mtime = _mtime(p)
  for d in reversed(dirs):
    mkdir(d)
  for d in reversed(dirs):
    _set_mtime(d, mtime)
  _set_mtime(p, p_mtime)
  #makedirs(dirname(dest), exist_ok=True)

# This works, but 'with' cannot cancel the upcoming block
# without throwing an exception.
#def _is_exception_active():
#  return sys.exc_info()[0] != None

# Does not check whether the stuff is really 'older'
def merge_older_stuff_into(targetdir, olderstuffdir):
  if exists(olderstuffdir):
    for dirpath, dirnames, filenames in walk(targetdir):
      olderdirpath = join(olderstuffdir, relpath(dirpath, targetdir))
      try:
        for older in listdir(olderdirpath):
          if not exists(join(dirpath, older)):
            rename(join(olderdirpath, older), join(dirpath, older))
      except(FileNotFoundError, NotADirectoryError):
        pass  #errors resulting from olderdirpath not being a directory
    rmtree(olderstuffdir)

def generic_do(sources, dests, build_system_sources, dirs_with_already_built_stuff = ()):
  """
  Version of 'do' that doesn't depend on a run* invocation.
  Normally the only dependencies on the run* invocation are
    * listing the set of files that everything depends on, and
    * listing the directories to get already-built files from.
  If you use this directly, you specify those explicitly instead.
  """
  fullsources = itertools.chain(build_system_sources, sources)
  latest_modified_source = max(_mtime(source) for source in fullsources)
  # Saying to generate a file when it's already there is elided.
  if all(map(exists, dests)):
    return
  # Make sure that directories keep consistent mtimes (for e.g.
  # rsync efficiency).
  parent_dir_mtimes = {}
  for dest in dests:
    # Helpfully auto-generate parent directories.
    makedirs_with_mtime(dirname(dest), latest_modified_source)
    parent_dir_mtimes[dirname(dest)] = _mtime(dirname(dest))
  for built in dirs_with_already_built_stuff:
    # Check == not >= so that reverting to an older source file version,
    # or manually modifying a dest file, will trigger a rebuild.
    up_to_date = all(_mtime_opt(join(built, dest)) == latest_modified_source for dest in dests)
    if up_to_date:
      for dest in dests:
        link(join(built, dest), dest)
      break
  else: #A loop's "else" runs if 'break' was not called
    # Call the building code.
    yield sources, dests
    # Make sure the dests will be seen as up-to-date.
    for dest in dests:
      _set_mtime(dest, latest_modified_source)
  for parent_dir, mtime in parent_dir_mtimes.items():
    _set_mtime(parent_dir, max(mtime, latest_modified_source))

def run_basic(builds_dir, build_system_sources):
  """
  Usage:

  for building_dir, do in run_basic(builds_dir, build_system_sources):
    ...
    # As many times as you like:
    for [src], [dest] in do([whatever source file], [join(building_dir, filepath)]):
      create dest from src
    ...

  Multiple source and/or destination files for a single operation are permitted.
  The use of 'for' is misleading.  The run_basic 'for loop' runs exactly once,
  and the 'do' 'for loops' run zero or one times (zero if the destination
  files are all up-to-date with the source files).  'do' is the conventional
  name for the special function, but its name is your choice.  If you
  accidentally omit a source you use in the 'do' block from the list of sources,
  then change the contents of that source file, it may not automatically rebuild.

  Any directories needed for destination files passed to 'do' are automatically
  created.  All such directories, and all destination files (once created),
  have their mtime and ctime set to the maximum mtime of the source files.
  For the purposes of mtime and up-to-date-ness checking, build_system_sources
  are treated as sources for every single use of 'do'.

  Source files can be destination files from preceding uses of 'do'.

  All destination files must be inside the 'building_dir' provided by run_basic,
  which will be a directory within builds_dir.  This allows the build-system
  to keep track of previously built versions of files and provide them when
  their mtime indicates they're up-to-date.


  'for' is used because
  it allows 'do' to take an action at the beginning and end of the block
  and possibly not execute the block at all.  'with' comes close but always
  executes the block or throws an exception.  'while' could possibly work
  but is worse than 'for' in every way.  'lambda' only allows single-line
  bodies, and 'def' requires naming the body and placing it before the list
  of source/destination files.  'if' can't take an action at the end of the
  block.  'try/except/finally' would be quite clunky.  Class definitions
  are inapplicable, and no other kinds of compound expression exist in Python.
  'def' with a decorator (
    @do(['src'], ['dest'])
    def _([src], [dest]):
      ...
  ) doesn't actually allow pattern-matching in the arguments of the def,
  and requires three lines where two might do.  So, despite the absurdity of
  'for', the syntax goes like:
    for [src], [dest] in do(['src'], ['dest']):
      ...
  """
  dirs_with_already_built_stuff = []
  builds_dir = abspath(builds_dir)
  build_dir = join(builds_dir, 'build')
  building_dir = join(builds_dir, 'building')
  building_old_dir = join(builds_dir, 'building-old')
  build_system_sources = [abspath(p) for p in build_system_sources]
  makedirs(builds_dir, exist_ok=True)
  if exists(build_dir):
    dirs_with_already_built_stuff.append(build_dir)
  # If there is a stale 'building' directory
  # then move it to or merge it with 'building-old'.
  if exists(building_dir):
    merge_older_stuff_into(building_dir, building_old_dir)
    rename(building_dir, building_old_dir)
  if exists(building_old_dir):
    dirs_with_already_built_stuff.append(building_old_dir)
  mkdir(building_dir)
  _set_mtime(building_dir, max(_mtime(source) for source in build_system_sources))
  # 'do': callback used to run a build rule if rebuild is needed.
  def do(sources, dests):
    return generic_do(sources, dests, build_system_sources, dirs_with_already_built_stuff)
  yield building_dir, do
  # Success: move the build to the completed-build location; clean up.
  if exists(building_old_dir): rmtree(building_old_dir)
  if exists(build_dir): rmtree(build_dir)
  rename(building_dir, build_dir)



# hmm what about (optionally) cleanly copying source using `git clone`

exclude_files_default_re = re.compile('~$|\.(swp|new|kate-swp)$|(^|/)(\.git|__pycache__|_darcs|\.svn|\.hg)(/|$)')
def exclude_files_default(f): return bool(exclude_files_default_re.search(f))
def run(srcdir, build_system_sources, builds_dir = None, exclude_src_files = exclude_files_default):
  """
  Like run_basic(), but:
  * Indicates building_dir by chdir'ing into it for the duration of
    the 'for' block, rather than yielding building_dir.
  * Before running the 'for' block, copies source files from srcdir to
    building_dir/src (except files that return True from exclude_src_files,
    which defaults to excluding some editor temp files and VCS directories),
    so that running commands that accidentally leave around build products
    next to source files will only damage/pollute the build directory, not
    the source directory.
  * Chooses builds_dir by default to be srcdir/../+xxxxxx-builds where xxxxxx
    is basename(srcdir), or you can specify builds_dir yourself.

  Usage:
  for do in run(srcdir, build_system_sources):
    ...
    # As many times as you like:
    for [src], [dest] in do([join('src', whatever source file)], [whatever dest]):
      create dest from src
    ...
  """
  srcdir = abspath(srcdir)
  if srcdir == '/':
    raise OSError("You can't use / as your src dir in this wrapper because it would obviously have to include the build dir and be copied into itself!")
  if builds_dir == None:
    builds_dir = join(dirname(srcdir), '+' + basename(srcdir) + '-builds')
  for building_dir, do in run_basic(builds_dir, build_system_sources):
    with utils.pushd(building_dir):
      # set up src
      buildsrcdir = 'src' #join(building_dir, 'src')
      for filepath in utils.relpath_files_under(srcdir):
        if not exclude_src_files(filepath):
          for [src], [dest] in do([join(srcdir, filepath)], [join(buildsrcdir, filepath)]):
            copyfile(src, dest)
      # run the build
      yield do


