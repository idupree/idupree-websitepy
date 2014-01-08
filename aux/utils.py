
import os, sys, hashlib, re, gzip
from os.path import relpath, join

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
                 else list(set(relation(i) for i in set(initial))))
    else:
      newdeps = [initial] if always_include_base_case else list(relation(initial))
    for newdep in popiter(newdeps):
      if newdep not in deps:
        yield newdep; deps.add(newdep)
        newdeps.extend(relation(newdep))
  return ret

# Of the common hash functions, sha224 and sha384 are less vulnerable to
# length extension attacks, and don't have many corresponding downsides, so prefer
# them.  On 64-bit hosts, sha384 is faster.
def sha384file(path):
  # http://stackoverflow.com/questions/1131220/get-md5-hash-of-big-files-in-python
  h = hashlib.sha384()
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
  binarystr = 'b' if isbinary else ''
  with open(infile, 'r'+binarystr) as f:
    contents = f.read()
  with open(outfile, 'w'+binarystr) as f:
    f.write(re.sub(string=contents, *sub_args, **sub_kwargs))

def gzip_omitting_metadata(infile, outfile):
  """
  Reads infile, gzips it, and writes the gzipped version to outfile.
  The gzip metadata 'filename' is left empty and 'mtime' is set to 0
  in Unix time (which is 1970).  There is no reason to include this
  metadata in "Content-Encoding: gzip" files, but the gzip file format
  contains those fields.
  """
  with open(infile, 'rb') as f_in:
    with open(outfile, 'wb') as f_out:
      with gzip.GzipFile(filename='', fileobj=f_out, mtime=0) as f_gzip:
        #per python docs http://docs.python.org/3/library/gzip.html
        f_gzip.writelines(f_in)

def read_file_text(path):
  with open(path, 'r') as f:
    return f.read()
def read_file_binary(path):
  with open(path, 'rb') as f:
    return f.read()

def write_file_text(path, data):
  with open(path, 'w') as f:
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

def relpath_files_under(rootpath):
  for dirpath, dirnames, filenames in os.walk(rootpath):
    for f in filenames:
      yield relpath(join(dirpath, f), rootpath)

def relpath_dirs_under(rootpath):
  for dirpath, dirnames, filenames in os.walk(rootpath):
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

