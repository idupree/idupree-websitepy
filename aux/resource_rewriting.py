
import re, hashlib, base64
from os.path import join, relpath, exists, normpath, dirname

import buildsystem, urlregexps, utils
import secrets


def direct_rr_deps_of_file(rr_ref_re, fpath, site_files_prefix):
  fdirname = dirname(fpath)
  contents = utils.read_file_binary(fpath)
  for match in re.finditer(rr_ref_re, contents):
    rel_ref = match.group('ref').decode('utf-8')
    if rel_ref[:1] == '/': ref = site_files_prefix+rel_ref
    else: ref = join(fdirname, rel_ref)
    yield normpath(ref)

def resolve_rr_deps_of_file(rr_ref_re, fpath, fpathout, f, site_files_prefix):
  fdirname = dirname(fpath)
  contents = utils.read_file_binary(fpath)
  def g(match):
    rel_ref = match.group('ref').decode('utf-8')
    if rel_ref[:1] == '/': ref = site_files_prefix+rel_ref
    else: ref = join(fdirname, rel_ref)
    return f(normpath(ref)).encode('utf-8')
  contentsout = re.sub(rr_ref_re, g, contents)
  utils.write_file_binary(fpathout, contentsout)


class ResourceRewriter(object):
  """
  Constructing a ResourceRewriter will compute the dependency information,
  then you can extract it using query functions and/or create rewritten
  versions of files using rewrite().
  """
  def __init__(
      self,
      do,
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
          f)
      ):
    """
    Expects 'do' to be from a current buildsystem.run() invocation.

    Expects (join(site_source_prefix, f) for f in rewritable_files) to be existent files
    that can contain links to rewrite.  Also expects all linked resources to exist.

    Creates and caches information in rr_cache_dir.
    """
    self._do = do
    self._rewritable_files = rewritable_files = frozenset(rewritable_files)
    self._referenced_resource_files = set()
    self._site_source_prefix = site_source_prefix
    self._rr_cache_dir = rr_cache_dir
    self._rr_ref_re = rr_ref_re
    self._rr_path_rewriter = rr_path_rewriter
    direct_deps_dir = self._direct_deps_dir = join(rr_cache_dir, 'direct-deps')
    transitive_deps_dir = self._transitive_deps_dir = join(rr_cache_dir, 'transitive-deps')
    hash_dir = self._hash_dir = join(rr_cache_dir, 'hash')
    hash_incl_deps_dir = self._hash_incl_deps_dir = join(rr_cache_dir, 'hash-incl-deps')
    rewritten_resource_name_dir = self._rewritten_resource_name_dir = join(rr_cache_dir, 'rewritten-resource-name')
    for f in rewritable_files:
      for [src], [dest] in do([join(site_source_prefix, f)], [join(direct_deps_dir, f)]):
        #todo assert no deps contain \n?
        direct_deps = [relpath(dd, site_source_prefix) for dd in
                       direct_rr_deps_of_file(rr_ref_re, src, site_source_prefix)]
        utils.write_file_text(dest, serialize_path_set(direct_deps))
      for dd in self.recall_direct_deps(f):
        self._referenced_resource_files.add(dd)
        for [src], [dest] in do([join(site_source_prefix, dd)], [join(hash_dir, dd)]):
          utils.write_file_binary(dest, utils.sha384file(src).digest())
    self._referenced_resource_files = frozenset(self._referenced_resource_files)
    for f in rewritable_files:
      # todo it is possible to do more work-sharing than this for more efficiency
      transitive_deps = set(utils.make_transitive(self.recall_direct_deps)(f))
      # todo would it make sense to depend on the nonexistence of a file?
      # luckily such nonexistence is pretty much only accidental here
      for _, [dest] in do(filter(exists, [join(direct_deps_dir, path) for path in {f} | transitive_deps]),
                          [join(transitive_deps_dir, f)]):
        utils.write_file_text(dest, serialize_path_set(transitive_deps))
    for f in utils.relpath_files_under(hash_dir):
      incl_deps = self.recall_transitive_deps_including_self(f)
      incl_dep_sha_files = [join(hash_dir, dep) for dep in incl_deps]
      for _, [dest] in do(incl_dep_sha_files, [join(hash_incl_deps_dir, f)]):
        incl_dep_shas = ([secrets.rr_hash_random_bytes] +
            [utils.read_file_binary(dep) for dep in incl_dep_sha_files])
        incl_deps_sha = hashlib.sha384(b''.join(incl_dep_shas)).digest()
        utils.write_file_binary(dest, incl_deps_sha)
      for [src], [dest] in do([join(hash_incl_deps_dir, f)], [join(rewritten_resource_name_dir, f)]):
        hashdigest = utils.read_file_binary(src)
        utils.write_file_text(dest, rr_path_rewriter(f, hashdigest))

  def recall_direct_deps(self, f):
    """do() wise, this depends only on f."""
    try: return deserialize_paths(utils.read_file_text(join(self._direct_deps_dir, f)))
    except FileNotFoundError: return []
  def recall_transitive_deps(self, f):
    """do() wise, this depends on f and all its rewritable transitive dependencies."""
    try: return deserialize_paths(utils.read_file_text(join(self._transitive_deps_dir, f)))
    except FileNotFoundError: return []
  def recall_transitive_deps_including_self(self, f):
    """do() wise, this depends on f and all its rewritable transitive dependencies."""
    return sorted(set(self.recall_transitive_deps(f)) | {f})

  def recall_hash(self, f):
    """do() wise, this depends only on f."""
    return utils.read_file_binary(join(self._hash_dir, f))
  def recall_transitive_hash(self, f):
    """do() wise, this depends on f and all its rewritable transitive dependencies."""
    return utils.read_file_binary(join(self._hash_incl_deps_dir, f))

  def recall_rewritten_resource_name(self, f):
    """do() wise, this depends on f and all its rewritable transitive dependencies."""
    return utils.read_file_text(join(self._rewritten_resource_name_dir, f))

  #def recall_all_rewritable_files(self):
  def recall_all_needed_resources(self):
    """do() wise, this depends only on all rewritable_files."""
    return self._referenced_resource_files
    

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
    for f in self._rewritable_files:
      incl_deps = [join(self._site_source_prefix, g)
                   for g in self.recall_transitive_deps_including_self(f)]
      for _, [dest] in self._do(incl_deps, [join(dest_dir, f)]):
        resolve_rr_deps_of_file(self._rr_ref_re,
          join(self._site_source_prefix, f), dest, resolver,
          self._site_source_prefix)
    if copy_nonrewritable_resources != None:
      for f in self._referenced_resource_files:
        if f not in self._rewritable_files:
          for [src], [dest] in self._do(
                [join(self._site_source_prefix, f)], [join(dest_dir, f)]):
            copy_nonrewritable_resources(src, dest)
    if copy_remaining_files_in_site_source_prefix != None:
      for f in utils.relpath_files_under(self._site_source_prefix):
        if f not in self._rewritable_files and f not in self._referenced_resource_files:
          for [src], [dest] in self._do(
                [join(self._site_source_prefix, f)], [join(dest_dir, f)]):
            copy_remaining_files_in_site_source_prefix(src, dest)
          


def serialize_path_set(paths): return '\n'.join(sorted(set(paths)))
def deserialize_paths(text): return [] if text == '' else text.split('\n')


