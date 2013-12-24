
import os, re
from os.path import join, normpath

exclude_dirs_default_set = set(('.git', '__pycache__'))
def exclude_dirs_default(d): return d in exclude_dirs_default_set
exclude_files_default_re = re.compile('~$|(^|/)\..*\.swp$')
def exclude_files_default(f): return bool(exclude_files_default_re.search(f))


# Possibly TODO i could make '/**/' be able to match
# no directories in between, which is apparently conventional
# and probably useful. A logic behind this: a//b is valid to mean a/b.

def glob_re_str(globstr):
  return \
    re.sub(r'\?', '([^/])',
    re.sub(r'(\(\[\^\/\]\*\)){2}', '(.*)',
    re.sub(r'\*', '([^/]*)',
    re.sub(r'([][.^$+{}\\|()])', r'\\\1', globstr))))
    
def globre(globstr):
  """
  Glob features:
    ? = single non-/ character
    * = any number of non-/ characters
    ** = any number of any characters
  returns: compiled regex
  """
  return re.compile('^' + glob_re_str(globstr) + '$')

def globdirprefixre_str(globstr):
  s = glob_re_str(globstr)
  s = re.sub(r'\(\.\*\).*$', '.*', s)
  s, n = re.subn(r'/(?!\])', '(?:/', s)
  s = s + n*')?'
  return s
def globdirprefixre(globstr):
  """
  Given a glob str that fits the rules of globre(), returns a regex
  that matches any directory that (without checking the filesystem)
  might possibly contain something that matches the glob.
  """
  return re.compile('^' + globdirprefixre_str(globstr) + '$')





class Glob(str):
  def sub(self, substitute):
    return self.match.expand(substitute)

def fglob(globstr, directory = '.', exclude_dirs = exclude_dirs_default, exclude_files = exclude_files_default):
  r = globre(globstr)
  rd = globdirprefixre(globstr)
  for dirpath, dirnames, filenames in os.walk(directory):
    dirnames[:] = [d for d in dirnames if
                   not exclude_dirs(d) and rd.search(normpath(join(dirpath, d)))]
    for filename in filenames:
      if not exclude_files(filename):
        fpath = normpath(join(dirpath, filename))
        match = r.search(fpath)
        if match != None:
          ret = Glob(fpath)
          ret.match = match
          yield ret

def globstr(globstr, string):
  match = globre(globstr).search(string)
  if match != None:
    ret = Glob(string)
    ret.match = match
    return ret
  return None

def globresub(globstr, substitute, orig):
  return globre(globstr).search(orig).expand(substitute)

