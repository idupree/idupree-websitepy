
import os, sys, hashlib, re, gzip, random
from os.path import relpath, isdir, basename

# We use forward slashes for paths even on Windows
# in order for consistency with URLs.
# For now, still use os.path.join instead of posixpath.join
# in case we're relying on correct behavior with absolute
# Windows paths.  Also consider integrating this with
# urljoin using heuristics?
def join(*f):
  return os.path.join(*f).replace('\\', '/')

def normpath(f):
  return os.path.normpath(f).replace('\\', '/')

def subPrematchedText(matches, replacement, originalText):
  """
  Returns: originalText with matches replaced by replacements.

  matches: iterable collection of re.Match objects
  replacement: function or template-string as in re.sub()
  originalText: the exact string that the Matches were created from
        (exact since string indexing by Match.begin()/end() is used).

  Works on all-bytes or all-str objects equally well.
  """
  if isinstance(replacement, (str, bytes)):
    replacementTemplate = replacement
    replacement = lambda match: match.expand(replacementTemplate)

  resultBuilder = []
  leftOffAtInFileIdx = 0
  for match in matches:
    resultBuilder.append(originalText[leftOffAtInFileIdx : match.start()])
    resultBuilder.append(replacement(match))
    leftOffAtInFileIdx = match.end()
  resultBuilder.append(originalText[leftOffAtInFileIdx:])
  return type(originalText)().join(resultBuilder)


def popiter(collection):
  try:
    while True:
      yield collection.pop()
  except (IndexError, KeyError):
    pass

def make_transitive(relation, always_include_base_case = False, multiple_base_cases = False):
  """
  relation: a function from a single object to an iterable set[1] of objects[2]
  returns : a function from a single object[4] to an iterable set[3] of objects
  always_include_base_case: if True, the returned function's returned set
    will include the returned function's argument even if repeating the function
    on the argument never produces the argument.
  
  The returned function applies f not just once, but repeatedly to all
  its returned objects.  It collects the set of objects that have been
  seen in the results of f until there are no more new returned objects.
  
  make_transitive could equivalently be a two-argument function,
  but something seemed elegant about it being an endomorphism.
  
  examples:
  modulo:
  >>> sorted(make_transitive(lambda x: [(x + 1) % 3])(7))
  [0, 1, 2]

  substrings:
  >>> sorted(make_transitive(lambda s: [s[1:], s[:-1]])('abcd'))
  ['', 'a', 'ab', 'abc', 'b', 'bc', 'bcd', 'c', 'cd', 'd']
  >>> sorted(make_transitive(lambda s: [s[1:], s[:-1]], True)('abcd'))
  ['', 'a', 'ab', 'abc', 'abcd', 'b', 'bc', 'bcd', 'c', 'cd', 'd']

  [1] any iterable will do; duplicates will be ignored
  [2] these objects must be hashable
  [3] not actually type 'set', but contains no duplicates
  [4] or a collection of objects, if multiple_base_cases is True
  """
  def ret(initial):
    deps = set()
    if multiple_base_cases:
      newdeps = (list(set(initial)) if always_include_base_case
                 else list(set().union(*(relation(i) for i in set(initial)))))
    else:
      newdeps = [initial] if always_include_base_case else list(relation(initial))
    for newdep in popiter(newdeps):
      if newdep not in deps:
        yield newdep; deps.add(newdep)
        newdeps.extend(relation(newdep))
  return ret

characters_that_are_easy_to_read_and_type = '23456789abcdefghijkmnpqrstuvwxyz'
alphanumeric_characters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
def alnum_secret(length = 22):
  """
  The default length of 22 gives at least 128 bits of entropy
  (entropy = log2(62**length))
  """
  rng = random.SystemRandom()
  return ''.join(rng.choice(alphanumeric_characters) for _ in range(length))

def sha384file(path):
  """
  Returns a hashlib hash object giving the sha384 of the argument
  file's contents.

  Hashes directory contents as a sequence of NUL-character-terminated
  directory entries (doesn't use the contents of those files, just
  their names in non-localized string order (which is alphabetical-ish)).

  Why SHA-384?  It is the best function available in hashlib. (As of this
  writing, SHA-3 isn't in hashlib: august 2015 / python 3.4.)
  sha224 and sha384 are less vulnerable to length extension attacks than
  the others, and don't have many corresponding downsides.  sha384 is
  faster on 64-bit computers (which I develop on), and has more result bits
  (for the unlikely chance that matters), so use sha384.
  """
  # http://stackoverflow.com/questions/1131220/get-md5-hash-of-big-files-in-python
  h = hashlib.sha384()
  if isdir(path):
    h.update(b''.join(p.encode()+b'\0' for p in sorted(os.listdir(path))))
  else:
    with open(path, 'rb') as f:
      for chunk in iter(lambda: f.read(2**20), b''):
        h.update(chunk)
  return h

def file_re_sub(infile, outfile, *sub_args, **sub_kwargs):
  """
  Calls re.sub(...) on the contents of infile and writes it to outfile.
  The arguments to sub are passed after infile and outfile.
  The file is opened in text or binary mode based on whether the
  pattern is text or binary.
  """
  pattern = sub_args[0] if len(sub_args) > 0 else sub_kwargs['pattern']
  pattern = pattern if isinstance(pattern, (str, bytes)) else pattern.pattern
  isbinary = isinstance(pattern, bytes)
  old_contents = (read_file_binary if isbinary else read_file_text)(infile)
  new_contents = re.sub(string=old_contents, *sub_args, **sub_kwargs)
  (write_file_binary if isbinary else write_file_text)(outfile, new_contents)

def gzip_omitting_metadata(infile, outfile):
  """
  Reads infile, gzips it at the maximum compression level, and writes
  the gzipped version to outfile.

  The gzip metadata 'filename' is left empty and 'mtime' is set to 0
  in Unix time (which is 1970).  An example situation you'd want this:

  For gzip-encoded data sent with "Content-Encoding: gzip",
  this metadata goes unused, and possibly wastes bandwidth or
  leaks information that wasn't intended to be published
  (most likely unimportant information, admittedly).
  """
  with open(infile, 'rb') as f_in:
    with open(outfile, 'wb') as f_out:
      with gzip.GzipFile(filename='', fileobj=f_out, mtime=0, compresslevel=9) as f_gzip:
        #per python docs http://docs.python.org/3/library/gzip.html
        f_gzip.writelines(f_in)

def read_file_text(path):
  with open(path, 'r', encoding='utf-8') as f:
    return f.read()
def read_file_binary(path):
  with open(path, 'rb') as f:
    return f.read()

def write_file_text(path, data):
  with open(path, 'w', encoding='utf-8') as f:
    return f.write(data)
def write_file_binary(path, data):
  with open(path, 'wb') as f:
    return f.write(data)


def write_stdout_binary(data):
  try: #python3
    sys.stdout.buffer.write(data)
  except AttributeError: #python2
    sys.stdout.write(data)

class pushd(object):
  def __init__(self, target):
    self.target = target
  def __enter__(self):
    self.source = os.getcwd()
    os.chdir(self.target)
  def __exit__(self, type, value, traceback):
    os.chdir(self.source)

def files_under(rootpath):
  for dirpath, dirnames, filenames in os.walk(rootpath):
    for f in filenames:
      yield join(dirpath, f)

def relpath_files_under(rootpath):
  for dirpath, dirnames, filenames in os.walk(rootpath):
    for f in filenames:
      yield relpath(join(dirpath, f), rootpath)

default_vcs_dirs = {'.git', '.hg', '.bzr', '.svn', '__pycache__'}
def relpath_files_under_excluding_vcs_etc(rootpath, vcs_dirs = default_vcs_dirs):
  for dirpath, dirnames, filenames in os.walk(rootpath):
    if basename(dirpath) in vcs_dirs:
      dirnames[:] = []
    else:
      for f in filenames:
        yield relpath(join(dirpath, f), rootpath)

def relpath_dirs_under(rootpath):
  for dirpath, dirnames, filenames in os.walk(rootpath):
    yield relpath(dirpath, rootpath)

def relpath_dirs_under_excluding_vcs_etc(rootpath, vcs_dirs = default_vcs_dirs):
  for dirpath, dirnames, filenames in os.walk(rootpath):
    if basename(dirpath) in vcs_dirs:
      dirnames[:] = []
    else:
      yield relpath(dirpath, rootpath)

# for python2/3 doctest compatibility, and general doctest readability,
# use 'testprint'
class Shown(object):
  def __init__(self, string):
    self.string = string
  def __str__(self):
    return self.string
  def __repr__(self):
    return self.string

def destrbytes(data):
  if isinstance(data, list):
    return [destrbytes(d) for d in data]
  if isinstance(data, tuple):
    return tuple(destrbytes(d) for d in data)
  if isinstance(data, bytes):
    return Shown(data.decode('utf-8'))
  if isinstance(data, str):
    return Shown(data)
  else:
    raise "implement this"

def testprint(data):
  print(destrbytes(data))

