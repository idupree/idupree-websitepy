
import re, hashlib, base64, os, sys
from os.path import exists, dirname, basename, isdir

from . import urlregexps
from . import utils
from .utils import join, normpath, abspath, relpath
# from . import buildsystem  #not directly used

class RewriterError(Exception):
  def __init__(self, value):
    self.value = value
  def __str__(self):
    return repr(self.value)

def joinif(a, b):
  if a and b: return join(a, b)
  elif a: return a
  else: return b

def direct_rr_deps_of_file(rr_ref_re, fpath, site_files_prefix, origins_to_assume_contain_the_resources):
  fdirname = dirname(fpath)
  contents = utils.read_file_binary(fpath)
  for match in re.finditer(rr_ref_re, contents):
    rel_ref = match.group('ref').decode('utf-8')
    origin_match = re.search(r'^(?:https?:)?//([^/]+)(.*)$', rel_ref)
    if origin_match:
      protocolless_origin = origin_match.group(1)
      if protocolless_origin not in origins_to_assume_contain_the_resources:
        #sys.stderr.write("WARNING: origin we don't know how to rewrite\n" +
        raise RewriterError("ERROR: " + repr(fpath) + ":\n" +
                "  origin we don't know how to rewrite:\n" +
          "    " + repr(protocolless_origin) + "\n" +
          "  in " + repr(rel_ref) + "\n" +
          "  Origin not listed in origins_to_assume_contain_the_resources:\n" +
          "  " + repr(origins_to_assume_contain_the_resources) + "\n")
      rel_ref = origin_match.group(2)
    #rel_ref = re.sub(r'^(?:https?:)?//[^/]+', '', rel_ref)
    #rel_ref = re.search(r'^((https?:)?//([^/]+))?(.*)$', '', rel_ref)
    if rel_ref[:1] == '/': ref = site_files_prefix+rel_ref
    else: ref = join(fdirname, rel_ref)
    yield normpath(ref)

def resolve_rr_deps_of_file(rr_ref_re, fpath, fpathout, f, site_files_prefix):
  fdirname = dirname(fpath)
  contents = utils.read_file_binary(fpath)
  def g(match):
    rel_ref = match.group('ref').decode('utf-8')
    origin_match = re.search(r'^((?:https?:)?//[^/]+)(.*)$', rel_ref)
    if origin_match:
      origin = origin_match.group(1)
      rel_ref = origin_match.group(2)
    else:
      origin = ''
    if rel_ref[:1] == '/': ref = site_files_prefix+rel_ref
    else: ref = join(fdirname, rel_ref)
    result = f(normpath(ref))
    # some/dir/?rr keeps the trailing slash when rewritten:
    if ref[-1:] == '/' and result[-1:] != '/':
      result += '/'
    result = origin + result
    return result.encode('utf-8')
  contentsout = re.sub(rr_ref_re, g, contents)
  utils.write_file_binary(fpathout, contentsout)


# random hex of length equal to a sha384 hash,
# so it's statistically unlikely to be the same
# as any hash of a guessable real text.
hash_for_nonexistent_file = b'dc02289afc4d6329d8886f13d6c88786488c69c5886ad8ec3df9dc5546c34f1da64740b521e63804d457339c977d29aa'

class ResourceRewriter(object):
  """
  Constructing a ResourceRewriter will compute the dependency information,
  then you can extract it using query functions and/or create rewritten
  versions of files using rewrite().
  """
  def __init__(
      self,
      *,
      rewritable_files,
      site_source_prefix = '.',
      rr_cache_dir = 'rr',
      rr_ref_re = br'(?<!'+urlregexps.urlbyte+br')'+
                  br'(?P<ref>'+urlregexps.urlbytes+br')\?rr'+
                  br'(?!'+urlregexps.urlbyte+br')',
      rr_path_rewriter = lambda f, hashdigest:
        # Attempt to keep the base filename before the hash and the file-type
        # extensions after the hash, for general friendliness.
        re.sub(
          r'^((?:.*/)?\.?[^/.]+)((?:\.[^/]*)?)$',
          r'\1.'+base64.urlsafe_b64encode(hashdigest)[:15].decode('ascii')+r'\2',
          f),
      do = None,
      hashed_data_prepend = b'',
      origins_to_assume_contain_the_resources = set()
      ):
    """
    Must be called with keyword arguments.  Most have defaults but you must specify
    rewritable_files, which says the location of the files that you want to rewrite.

    Expects (join(site_source_prefix, f) for f in rewritable_files) to be existent files
    that can contain links to rewrite.  Also expects all linked resources to exist.

    Creates and caches information in rr_cache_dir.

    Expects 'do' to be from a current buildsystem.run() invocation,
    or None (default) for no caching of information between runs.

    hashed_data_prepend can be set to a randomly generated secret byte-string.
    If not everything on your website is public, this may moderately reduce
    the chance that someone can find the non-public stuff by guessing the
    hashes or the hashed file contents.  If you want ResourceRewriter to
    produce consistent hashes -- so that, for example, diff or rsync between
    new versions and old versions work better -- then you should pass the
    same value every time.  One reasonable way to get such random data is
    our utils module's alnum_secret: alnum_secret().encode('ascii')

    origins_to_assume_contain_the_resources is a set of places you can write
    absolute links to with ?rr that will be rewritten but keep the same domain.
    This is needed for <meta name="og:image"> because twitter and facebook
    do not accept a relative path in its contents. If only supporting facebook,
    you can use <link rel="image_src"> instead, but twitter needs that to be
    an full URL even in <link>.  A downside of full paths is they won't point
    to your testing environment when used in the testing environment, they won't
    adapt to the refering page's http/https-ness, etc.
    Example: origins_to_assume_contain_the_resources = {'www.example.com'}
    """
    if do == None:
      def do(srcs, dests):
        # This impl would set timestamps the way 'buildsystem' does, except
        # that it doesn't work when one of the srcs is a file "generated"
        # but not actually generated by writestore(). :
        #   return buildsystem.generic_do(srcs, dests, ())
        # We could record the timestamps ourselves, and/or use a temporary
        # directory (and clean up after it), but we currently don't.
        # This only matters for users of this module who are actually
        # calling .rewrite() rather than just extracting metadata.
        from os import makedirs
        for dest in dests: makedirs(dirname(dest), exist_ok=True)
        yield (srcs, dests)
      store = {}
      def readstore(f): return store[normpath(f)]
      def writestore(f, v): store[normpath(f)] = v
      io = { 'r': readstore, 'rb': readstore, 'w': writestore, 'wb': writestore }
    else:
      io = { 'r': utils.read_file_text, 'rb': utils.read_file_binary,
             'w': utils.write_file_text, 'wb': utils.write_file_binary }
    self._do = do
    self._io = io
    self._rewritable_files = rewritable_files = frozenset(rewritable_files)
    self._referenced_resource_files = set()
    self._site_source_prefix = site_source_prefix
    self._rr_cache_dir = rr_cache_dir
    self._rr_ref_re = rr_ref_re
    self._rr_path_rewriter = rr_path_rewriter
    referenced_and_rewritable_files = set(rewritable_files)
    # Changes to this Python file are moderately likely to change rewriting
    # behaviour, though none of the files this file includes are very
    # likely to.  So hash this file and include it in resource name hashes.
    this_file_hash = utils.sha384file(__file__).digest()
    for f in rewritable_files:
      for [src], [dest] in do([join(site_source_prefix, f)], [self._direct_deps_f(f)]):
        direct_deps = [relpath(dd, site_source_prefix) for dd in
                       direct_rr_deps_of_file(rr_ref_re, src, site_source_prefix,
                                              origins_to_assume_contain_the_resources)]
        io['w'](dest, serialize_path_set(direct_deps))
      self._referenced_resource_files.update(self.recall_direct_deps(f))
    def referenced_dir(f):
      if isdir(join(site_source_prefix, f)):
        for [src], [dest] in do([join(site_source_prefix, f)], [self._direct_deps_f(f)]):
          direct_deps = [relpath(join(src, dd), site_source_prefix) for dd in sorted(os.listdir(src))]
          io['w'](dest, serialize_path_set(direct_deps))
        self._referenced_resource_files.update(self.recall_direct_deps(f))
        return self.recall_direct_deps(f)
      else:
        return ()
    for _ in utils.make_transitive(referenced_dir,
        multiple_base_cases=True)(self._referenced_resource_files): pass
    for f in self._referenced_resource_files:
      if f not in rewritable_files and not isdir(join(site_source_prefix, f)):
        for [src], [dest] in do([join(site_source_prefix, f)], [self._direct_deps_f(f)]):
          io['w'](dest, serialize_path_set(()))
    self._referenced_resource_files = frozenset(self._referenced_resource_files)
    referenced_and_rewritable_files = frozenset(self._referenced_resource_files | rewritable_files)
    for f in referenced_and_rewritable_files:
      for [src], [dest] in do([join(site_source_prefix, f)], [self._hash_f(f)]):
        if exists(src):
          sha = utils.sha384file(src).digest()
        else:
          sha = hash_for_nonexistent_file
        io['wb'](dest, sha)
    for f in referenced_and_rewritable_files:
      # todo it is possible to do more work-sharing than this for more efficiency
      transitive_deps = set(utils.make_transitive(self.recall_direct_deps)(f))
      for _, [dest] in do([self._direct_deps_f(path) for path in {f} | transitive_deps],
                          [self._transitive_deps_f(f)]):
        io['w'](dest, serialize_path_set(transitive_deps))
    for f in referenced_and_rewritable_files:
      incl_deps = self.recall_transitive_deps_including_self(f)
      incl_dep_sha_files = [self._hash_f(dep) for dep in incl_deps]
      for _, [dest] in do(incl_dep_sha_files, [self._hash_incl_deps_f(f)]):
        incl_dep_shas = (
            [hashed_data_prepend, this_file_hash] +
            [io['rb'](dep) for dep in incl_dep_sha_files])
        incl_deps_sha = hashlib.sha384(b''.join(incl_dep_shas)).digest()
        io['wb'](dest, incl_deps_sha)
    # sorted() will process directories before their contents
    for f in sorted(referenced_and_rewritable_files):
      # Put the hash on the farthest self or ancestor directory that
      # is rr-referenced by anyone.
      f_base = f
      f_rest = None
      while dirname(f_base) in referenced_and_rewritable_files:
        f_rest = joinif(basename(f_base), f_rest)
        f_base = dirname(f_base)
      src = self._hash_incl_deps_f(f_base)
      dest = self._rewritten_resource_name_f(f)
      # Specifying this dependency fully is too hard now that it depends
      # on whether any rewritable file rr-links to each parent directory.
      # Use do() to create directories if necessary with a
      # reasonable-ish mtime, but then recompute the file regardless.
      for _ in do([src], [dest]):
        # Create file so that the buildsystem code won't get confused.
        # It will be overwritten soon anyway, regardless of how this do()
        # generates the file.
        io['w'](dest, '')
      hashdigest = io['rb'](src)
      io['w'](dest, joinif(rr_path_rewriter(f_base, hashdigest), f_rest))

  def _direct_deps_f(self, f):
    return join(self._rr_cache_dir, 'direct-deps', f)+'.deps'
  def _transitive_deps_f(self, f):
    return join(self._rr_cache_dir, 'transitive-deps', f)+'.deps'
  def _hash_f(self, f):
    return join(self._rr_cache_dir, 'hash', f)+'.hash'
  def _hash_incl_deps_f(self, f):
    return join(self._rr_cache_dir, 'hash-incl-deps', f)+'.hash'
  def _rewritten_resource_name_f(self, f):
    return join(self._rr_cache_dir, 'rewritten-resource-name', f)+'.name'

  def recall_direct_deps(self, f):
    """do() wise, this depends only on f."""
    return deserialize_paths(self._io['r'](self._direct_deps_f(f)))
  def recall_transitive_deps(self, f):
    """do() wise, this depends on f and all its rewritable transitive dependencies."""
    return deserialize_paths(self._io['r'](self._transitive_deps_f(f)))
  def recall_transitive_deps_including_self(self, f):
    """do() wise, this depends on f and all its rewritable transitive dependencies."""
    return sorted(set(self.recall_transitive_deps(f)) | {f})

  def recall_hash(self, f):
    """do() wise, this depends only on f."""
    return self._io['rb'](self._hash_f(f))
  def recall_transitive_hash(self, f):
    """do() wise, this depends on f and all its rewritable transitive dependencies."""
    return self._io['rb'](self._hash_incl_deps_f(f))

  def recall_rewritten_resource_name(self, f):
    """do() wise, this depends on f and all its rewritable transitive dependencies."""
    return self._io['r'](self._rewritten_resource_name_f(f))

  def recall_all_rewritable_files(self):
    return self._rewritable_files

  def recall_all_files_and_dirs_that_can_have_deps(self, required_files):
    return set(filter(
          lambda f: f in self._rewritable_files or isdir(join(self._site_source_prefix, f)),
          set().union(*(self.recall_transitive_deps_including_self(f)
                        for f in required_files if f in self._rewritable_files))))

  def recall_all_needed_resources(self, required_files, count_directories_as_resources=False):
    """do() wise, this depends on recall_all_files_and_dirs_that_can_have_deps(required_files)."""
    return set(filter(
          lambda f: count_directories_as_resources or not isdir(join(self._site_source_prefix, f)),
          set().union(*(self.recall_transitive_deps(f)
                        for f in required_files if f in self._rewritable_files))))

  def rewrite(self,
        dest_dir,
        resource_url_maker,
        copy_nonrewritable_resources=None,
        copy_remaining_files_in_site_source_prefix=None
        ):
    """
    Broadly, rewrite() mirrors site_source_prefix into dest_dir.
    It creates modified versions of every file listed in rewritable_files
      (or unmodified versions if they didn't happen to have any resource refs).
    If copy_nonrewritable_resources, it also copies referenced nonrewritable
      resource files (e.g. images) into into dest_dir.
    Resources' filenames are not changed to their rewritten version;
    only the references are changed.  This is partly because this code
    doesn't even know which files are intended to be accessed directly at a
    non-rewritten URL by someone browsing the web.

    dest_dir: the directory to mirror into
    resource_url_maker: a function that takes (f, recall_rewritten_resource_name(f))
      and returns the URL that should be substituted in place of the
      resource-ref text.  (TODO: consider providing the referencing file's name
      as well, although that can be iffy when JavaScript has a resource ref
      and is included by HTML files in different directories.)
    copy_nonrewritable_resources: a file-copying-ish function that takes a src and dest
      argument and creates dest based on src, e.g. shutil.copyfile or os.link.
      If None, no copying of files not listed in rewritable_files is done.
    copy_remaining_files_in_site_source_prefix: like 
    """
    def resolver(dep_path):
      orig_path = relpath(dep_path, self._site_source_prefix)
      new_path = self.recall_rewritten_resource_name(orig_path)
      return resource_url_maker(new_path, orig_path)
    already_copied = set()
    for f in self._rewritable_files:
      incl_deps = [join(self._site_source_prefix, g)
                   for g in self.recall_transitive_deps_including_self(f)]
      for _, [dest] in self._do(incl_deps, [join(dest_dir, f)]):
        resolve_rr_deps_of_file(self._rr_ref_re,
          join(self._site_source_prefix, f), dest, resolver,
          self._site_source_prefix)
      already_copied.add(f)
    if copy_nonrewritable_resources != None:
      for f in self._referenced_resource_files:
        if f not in already_copied and not isdir(join(self._site_source_prefix, f)):
          src = join(self._site_source_prefix, f)
          if exists(src):
            for _, [dest] in self._do([src], [join(dest_dir, f)]):
              copy_nonrewritable_resources(src, dest)
          already_copied.add(f)
    if copy_remaining_files_in_site_source_prefix != None:
      for f in utils.relpath_files_under(self._site_source_prefix):
        if f not in already_copied:
          for [src], [dest] in self._do(
                [join(self._site_source_prefix, f)], [join(dest_dir, f)]):
            copy_remaining_files_in_site_source_prefix(src, dest)
          already_copied.add(f)
          


def serialize_path_set(paths):
  assert(not any(re.search(r'[\r\n]', p) for p in paths))
  return '\n'.join(sorted(set(paths)))

def deserialize_paths(text):
  return [] if text == '' else text.split('\n')


