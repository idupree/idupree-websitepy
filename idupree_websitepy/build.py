
import os, os.path, sys, subprocess, re, base64, hashlib, mimetypes, copy
from os.path import join, dirname, normpath, exists
from urllib.parse import urljoin, urldefrag, urlparse
from distutils.spawn import find_executable

from . import buildsystem
from . import utils
from . import errdocs
from . import urlregexps
from . import resource_rewriting

cmd = subprocess.check_call

# TODO delete:
#cdn_resources_path = '//??????????.cloudfront.net/'
#scheme_and_domain = 'http://www.idupree.com'
#doindexfrom = set(map(lambda r: scheme_and_domain+r, ['/']))
#butdontindexfrom = set(map(lambda r: scheme_and_domain+r, ['/semiprivate-page']))

# fake_resource_route: prefixed to resource names to give them
# routes before they are rewritten to the actual resource-route prefix
# and contents-hash.
fake_resource_route = 'http://fake-rr.idupree.com/'
def is_fake_rr(route):
  return route[:len(fake_resource_route)] == fake_resource_route
def fake_rr_to_f(route):
  if is_fake_rr(route): return route[len(fake_resource_route):]
  else: return None

class SasscDefault: pass

class Config(object):
  def __init__(self, *,
    site_source_dir,
    build_output_dir = None,
    site_document_root_relative_to_source_dir = '.',
    pandoc_template_relative_to_source_dir = None,
    pandoc_command = 'pandoc',
    sassc_command = SasscDefault,
    list_of_compilation_source_files,
    canonical_scheme_and_domain = None,
    nocdn_resources_path = '/_resources/',
    doindexfrom,
    butdontindexfrom,
    optionally_secret_random_data = None,
    rr_hash_random_bytes = None,
    nginx_hash_random_bytes = None,
    test_host = None,
    test_port = None,
    test_host_header = None,
    # Setting to True can be slow on non-localhost connections if you
    # have a lot of data (e.g. images) on the site; all "True" tests
    # is that this library's Content-Length header code isn't buggy for
    # those things.
    test_all_content_lengths = False
    ):
    """
    os.path.join(site_source_dir, site_document_root_relative_to_source_dir):
      directory that contains your to-be-website-contents.
      You might make them be separate if you process some source files
      that you want to make it clear they won't be directly served to
      the user.  The document root *must* be within the source dir.

    build_output_dir: where to put build outputs. Defaults to
      a sibling of site_source_dir named +xxxxxx-builds where xxxxxx
      is basename(site_source_dir).  Its children will be 'build' and
      some temporary directory names meant to keep rebuilds more atomic
      (build failure doesn't destroy your old build data).

    pandoc_template_relative_to_source_dir: similarly. Used if specified
      and you have .md markdown content.

    pandoc_command: executable to use for pandoc (relevant if you have
      markdown files)

    list_of_compilation_source_files: used so the recompilation checker can
      check if your code is doing something different now. Make sure to include
      at least the file you're calling this code from.  For example,
          list_of_compilation_source_files =
            set(filter(
                lambda f: re.search('\.py$', f),
                set(utils.files_under('.'))))
      or you could use get_python_file_names_under() if applicable.

    canonical_scheme_and_domain: default none,
      example 'http://www.idupree.com'.  Used in Link: rel="canonical"
      HTTP headers if it's provided.

    nocdn_resources_path:
    serve all resources (images, CSS, etc) with paths prefixed with this
    path. ("nocdn" because this code used to support serving files through
    a CDN in a different way. If we bring back that feature, we'll see how
    that ends up being arranged like.)

    optionally_secret_random_data: bytes or str.  Used in some hashes
      to produce random strings that people shouldn't be able to guess.

      This should try to remain consistent from one run of this script to the
      next, in order to make tools like rsync and browser caching be able
      to recognize that files that haven't changed are still the same.

      If it's not a high-entropy random secret, then people may be able
      to discover some resource files on your website that aren't
      linked from anywhere, by guessing their URLs.

      If you desire extra control for some reason, you can separately
      specify random values in 'bytes' format for rr_hash_random_bytes
      and nginx_hash_random_bytes.
    """
    assert(not re.search(r'\.\.|^/', site_document_root_relative_to_source_dir))
    if pandoc_template_relative_to_source_dir != None:
      assert(not re.search(r'\.\.|^/', pandoc_template_relative_to_source_dir))
    self.site_source_dir = site_source_dir
    self.site_document_root_relative_to_source_dir = site_document_root_relative_to_source_dir
    self.site_document_root = join(site_source_dir, site_document_root_relative_to_source_dir)
    self.build_output_dir = build_output_dir
    self.pandoc_template_relative_to_source_dir = pandoc_template_relative_to_source_dir
    self.pandoc_command = pandoc_command
    if sassc_command != SasscDefault:
      self.sassc_command = sassc_command
    elif find_executable('sassc'):
      self.sassc_command = 'sassc'
    elif find_executable('sass'):
      self.sassc_command = 'sass'
    else:
      self.sassc_command = None

    self.list_of_compilation_source_files = list_of_compilation_source_files
    self.canonical_scheme_and_domain = canonical_scheme_and_domain
    # just for in this build script:
    # (should it always be something like the latter?)
    # (if so, figure out how that interacts with how doindexfrom/butdontindexfrom
    #  are specified!!)
    self.hypothetical_scheme_and_domain = canonical_scheme_and_domain or 'https://hypothetical.idupree.com'
    self.nocdn_resources_path = nocdn_resources_path
    self.doindexfrom = set(doindexfrom)
    self.butdontindexfrom = set(butdontindexfrom)
    if isinstance(optionally_secret_random_data, str):
      optionally_secret_random_data = optionally_secret_random_data.encode('utf-8')
    if optionally_secret_random_data == None:
      # 256 bits of public data that I generated with crypto random.
      # The only use of such public random data is that the hashes we create
      # will be different from hashes created not using these bits of data.
      # In any case, it doesn't hurt compared to using b''.
      optionally_secret_random_data = \
        b'rdtvsrzzokqozngqkdeafvksozujwikieiflltsezonabuxgmohjxek'
    if rr_hash_random_bytes == None:
      rr_hash_random_bytes = \
        hashlib.sha384(b'rr:'+optionally_secret_random_data).digest()
    if nginx_hash_random_bytes == None:
      nginx_hash_random_bytes = \
        hashlib.sha384(b'nginx:'+optionally_secret_random_data).digest()
    self.rr_hash_random_bytes = rr_hash_random_bytes
    self.nginx_hash_random_bytes = nginx_hash_random_bytes

    self.test_host = test_host
    self.test_port = test_port
    self.test_host_header = test_host_header
    self.test_all_content_lengths = test_all_content_lengths

def svg_to_png(src, dest, width, height):
  cmd(['inkscape', '--without-gui', '--export-png='+dest,
    '--export-background-opacity=0', '-w', str(width), '-h', str(height),
    str(src)])
  cmd(['optipng', dest])

def pngs_to_ico(png_srcs, dest):
  """
  The ICO format allows multiple PNGs[1] of different resolutions
  to be combined into one ICO file, with the context deciding which
  resolution gets used in any particular place.
  
  [1] (or some other bitmap formats, but PNG is probably the best)
  """
  cmd(['convert'] + png_srcs + [dest])

def dirname_of_this_library():
  return os.path.dirname(os.path.abspath(__file__))

def get_python_file_names_under(dirname):
  return set(filter(
      lambda f: re.search('\.py$', f),
      set(utils.files_under(dirname))))

def build(config, pre_action = None):
  """
  pass an instance of Config
  TODO: make more configurable
  TODO: fix utils.files_under parts and document
            what is required of the caller
  pre_action is a function. pre_action(do) happens before other stuff
  but gets to share the build-temp directory...
  """
  sources = (set(config.list_of_compilation_source_files) | 
             get_python_file_names_under(dirname_of_this_library()))
  for do in buildsystem.run(config.site_source_dir, sources,
                            config.build_output_dir):
    if pre_action != None:
      pre_action(do)

    route_metadata, rewriter = \
        custom_site_preprocessing(config, do)

    nginx_openresty(config, do, rewriter, route_metadata)

class RouteInfo(object):
  """
  status: numeric HTTP status code
  headers: list of pairs of str (header name, header value)
  file: 'site/'-relative path to a file containing the HTTP body
    for responding to this request, or None for no body
  worth_gzipping: whether to Vary:Accept-Encoding this
  http_redirect_to: a (possibly relative) URL.  Requires status 3xx.
    This is used instead of adding a Location: header because Location:
    can't be a relative URL in older standards (RFC 2616: HTTP 1.1)
    and is partly broken in a few settings[1] although new
    standards say it can be relative[2].
    Being relative is helpful for testing locally and
    for redirecting same-protocol (http vs https).
    [1] support is inconsistent in IE or some server setups?
        https://stackoverflow.com/questions/6948128/ie-doesnt-follow-redirect-gives-internet-explorer-cannot-display-the-webpage
        https://stackoverflow.com/questions/4096435/internet-explorer-not-following-relative-redirect-urls-across-domains
    [2] https://en.wikipedia.org/wiki/HTTP_location
        https://webmasters.stackexchange.com/questions/31274/what-are-the-consequences-for-using-relative-location-headers
        https://stackoverflow.com/questions/8250259/is-a-302-redirect-to-relative-url-valid-or-invalid
        http://fetch.spec.whatwg.org/
  """
  def __init__(self, status = None, headers = None,
               http_redirect_to = None,
               file = None, worth_gzipping = None):
    self.status = status
    self.headers = headers if headers != None else []
    self.http_redirect_to = http_redirect_to
    self.file = file
    self.worth_gzipping = worth_gzipping
#and have a base one provided by f's that is copy+added to by specific routes

def custom_site_preprocessing(config, do):
  """
  Returns route_metadata, rewriter

  Creates 'site/' from 'src/site/' and some custom rules.

  do : from buildsystem.py
  route_metadata : dict from URL string to RouteInfo.
  rewriter : resource_rewriting.ResourceRewriter
  """
  src_document_root = join('src', config.site_document_root_relative_to_source_dir)
  # The following are the path without any src/site/ or site/ prefix.
  # (Hmm, why *don't* the auxiliary dirs all have site/ under them in paths?
  #  It would mean less add/removing of path components.)
  files_to_consider = list(utils.relpath_files_under(src_document_root))
  # files_to_rewrite : files that have resource-rewritable links in them
  files_to_rewrite = set()
  # file_metadata : {file:RouteInfo} contains default RouteInfo for
  #   routes that use these files; for example, Content-Type.
  file_metadata = {}
  route_metadata = {}

  def add_route(route, f = None):
    assert(route not in route_metadata)
    # hmm file_metadata therefore shouldn't be updated after this is called,
    # because it wouldn't have an effect on the route's metadata then
    if f != None:
      route_metadata[route] = copy.deepcopy(file_metadata[f])
    else:
      route_metadata[route] = RouteInfo()

  def autohead(src, dest, canonical_url = None):
    #utils.file_re_sub(src, dest, b'{{:canonical}}', url.encode('utf-8'))
    # TODO test/allow alternate explicit icons.
    # My browsers don't fetch '/favicon.ico' at all.
    utils.file_re_sub(src, dest, br'((?:\n|^)[ \t]*)<!--AUTOHEAD-->',
      (br'\1<link rel="canonical" href="' + canonical_url.encode('utf-8') + b'" />'
        if canonical_url != None else b'') +
      br'\1<link rel="shortcut icon" href="/favicon.ico?rr" />'
      )
  def autoobfuscate(src, dest):
    """
    AUTO_OBFUSCATE_URL(addr example.com) --> mailto:addr@example.com obfuscated for
      use in an HTML href="".  Note: one obfuscation, newlines in the address,
      is not HTML-valid but still works in at least Firefox and Chromium and
      makes it harder for bots that just preprocess pages with &-decoding and
      case-folding.
    AUTO_OBFUSCATE_HTML(addr example.com) --> addr@example.com obfuscated for
      use in HTML body text.

    The source syntaxes are written without an @ and without mentioning the word "mail"
    in the hopes that if the source document is visible to the Web, or the replacement
    fails to work for some reason, it will still be difficult to automatically harvest
    the email address from the source.
    """

    # Percent encoding: not much use: https://code.google.com/p/chromium/issues/detail?id=335322
    # (Firefox (26) is fine, Chromium (31) not)
    #def obf_percent_encode_char(c):
    #  return b'%'+
    def obf_html_encode_char(c):
      return b'&#'+str(ord(c)).zfill(4).encode()+b';'
    def obf1(match):
      return (
        re.sub(br'(.)$', lambda m: b'\n\n'+obf_html_encode_char(m.group(1))+b'\n', match.group(1))+
        b'&#0064;\n\n'+
        re.sub(br'(.)\.(.)',
          lambda m: b'\n'+obf_html_encode_char(m.group(1))+b'&#0046;\n'+obf_html_encode_char(m.group(2))+b'\n',
          match.group(2)))
    def mailto_obf(match):
      return b'&#0109;aI&#x4c;tO&#0058;\n'+obf1(match)
    def html_obf(match):
      return re.sub(br'\n', b'<span\n></span\n>', obf1(match))
    utils.file_re_sub(src, dest,
      br'\bAUTO_OBFUSCATE_URL\(([^() \t\r\n]*) ([^() \t\r\n]*)\)',
      mailto_obf)
    utils.file_re_sub(dest, dest,
      br'\bAUTO_OBFUSCATE_HTML\(([^() \t\r\n]*) ([^() \t\r\n]*)\)',
      html_obf)


  def add_file(f, guess_mime_type = True):
    """
    Records some basic info about f, a file that might be used
    as a page and/or resource on the site.

    f is relative to site/
    """
    assert(f not in file_metadata)
    file_metadata[f] = RouteInfo(status=200, file=f)
    # TODO also gzip anything that benefits
    file_metadata[f].worth_gzipping = \
      bool(re.search(r'\.(html|css|js|svg|appcache)$', f))
    if re.search(r'\.(html|css|js|appcache)$', f):
      files_to_rewrite.add(f)
      # [Note_Superset]
      # (Relevant for deployments that put resources on a static content
      #  server that can't content-negotiate gzip-encoding.)
      #
      # It's easiest to gzip all rewritten files, because their resources
      # might also need to be gzipped-when-client-supports-it, and since
      # it makes deployment slightly simpler and almost all files with
      # links in them will benefit from gzipping.
      assert(file_metadata[f].worth_gzipping)
    if guess_mime_type:
      # mimetypes.guess_type guesses wrong here:
      if re.search(r'\.(pub)?key\.asc$', f):
        mime = 'application/pgp-keys'
      elif re.search(r'\.ico$', f):
        # https://en.wikipedia.org/wiki/ICO_%28file_format%29#MIME_type
        # http://stackoverflow.com/q/1444975
        mime = 'image/x-icon'
      else:
        mime, content = mimetypes.guess_type(f)
        if content != None or mime == None:
          mime = 'application/octet-stream'
      if re.search('^text/|[+/](?:xml|json)$|^application/javascript$', mime):
        mime += '; charset=utf-8'
      file_metadata[f].headers.append(('Content-Type', mime))

  def add_redirect(status, from_route, to):
    add_route(from_route)
    route_metadata[from_route].status = status
    route_metadata[from_route].http_redirect_to = to
    # Alternate implementation from http_redirect_to
    # that always redirects only to the canonical domain:
    #route_metadata[from_route].headers.append((
    #    'Location', urljoin(from_route, to)))

  for srcf in files_to_consider:
    src = join(src_document_root, srcf)
    route = None
    f = None
    if re.search(r'\.(html|md|rss|atom)$', srcf):
      is_markdown = re.search(r'\.md$', srcf)
      extless_path = re.sub(r'\.(html|md|rss|atom)$', '', srcf)
      f = extless_path+'.html'
      dest = join('site', f)
      # slight hack for index.html file
      domainrelative_route = re.sub('/index$', '/', '/'+extless_path)
      route = config.hypothetical_scheme_and_domain + domainrelative_route
      url = (config.canonical_scheme_and_domain + domainrelative_route
             if config.canonical_scheme_and_domain != None else None)
      if is_markdown:
        if config.pandoc_template_relative_to_source_dir != None:
          pandoc_template = join('src', config.pandoc_template_relative_to_source_dir)
          pandoc_templates = [pandoc_template]
        else:
          pandoc_templates = []
        for _ in do([src] + pandoc_templates, [dest]):
          cmd([config.pandoc_command, '--standalone'] +
              ['--template='+t for t in pandoc_templates] +
              ['-t', 'html5', '-o', dest, src])
          autohead(dest, dest, url)
          autoobfuscate(dest, dest)
      else:
        for _ in do([src], [dest]):
          autohead(src, dest, url)
          autoobfuscate(dest, dest)
    elif re.search(r'\.(scss|sass)$', srcf):
      f = re.sub(r'\.(scss|sass)$', '.css', srcf)
      # don't disturb precompiled scss:
      if exists(join(src_document_root, f)):
        f = None
      else:
        assert(config.sassc_command) #install `sassc` (preferred) or `sass`
        f_map = f+'.map'
        dest = join('site', f)
        #I don't have a scss dependency chaser, so I can't easily give
        #the correct set of dependencies to do(), but sassc is pretty fast
        #so I'll run it every time.
        # Creates both f and f_map:
        cmd([config.sassc_command, '--sourcemap', src, dest])
    elif re.search(r'\.(txt|asc|pdf|zip|tar\.(gz|bz2|xz)|appcache)$|^t\.gif$|^favicon.ico$|^haddock-presentation-2010/', srcf):
      f = srcf
      route = config.hypothetical_scheme_and_domain+'/'+f
      dest = join('site', f)
      for _ in do([src], [dest]):
        os.link(src, dest)
    elif re.search(r'\.(3[0-9][0-9])$', srcf):
      extless_path = re.sub(r'\.(3[0-9][0-9])$', '', srcf)
      # Hmm should 'index.301' be a thing? or '.301'? or just use dirname.301
      route = config.hypothetical_scheme_and_domain+'/'+extless_path
      # Alas, this code currently can't support redirecting to a resource. TODO
      add_redirect(int(srcf[-3:]), route, utils.read_file_text(src).strip())
      # Don't add the route again below
      route = None
    else:
      f = srcf
      dest = join('site', f)
      for _ in do([src], [dest]):
        os.link(src, dest)
    if f != None:
      add_file(f)
    if route != None:
      add_route(route, f)

  f = '404.html'
  for [], [dest] in do([], [join('site', f)]):
    utils.write_file_text(dest, errdocs.errdoc(404))
  add_file(f)
  file_metadata[f].status = 404

  # It's not super elegant calling the rewriter inside custom processing
  # rather than after, but it'll do.
  rewriter = resource_rewriting.ResourceRewriter(
    rewritable_files = files_to_rewrite,
    site_source_prefix = 'site',
    hashed_data_prepend = config.rr_hash_random_bytes,
    do=do)

  nonresource_routes = {route_ for route_ in route_metadata}
  for f in rewriter.recall_all_needed_resources(
      route_metadata[f].file for f in nonresource_routes if route_metadata[f].file):
    add_route(fake_resource_route+f, f)
  resource_routes = {route_ for route_ in route_metadata} - nonresource_routes

  broken_link_found = False
  #TODO use do() to make this cached in a file.
  def find_internal_links(route):
    """
    Given a route, returns (an estimate of) all routes that
    it links to in any manner (href or resource).  Won't find links
    that are neither in an "href" nor marked as a rewritable-resource link
    (erring on the side of not finding links since finding links risks
    half-private pages being Google-indexable, while finding no links
    in weird cases just means weird enough things won't be Google-indexable
    unless I explicitly mark them into that list).
    """
    result = set()
    f = route_metadata[route].file
    # TODO if we except some HTML files from rewriting then this
    # will be wrong:
    if f not in files_to_rewrite:
      return result
    contents = utils.read_file_binary(join('site', f))
    for href in re.finditer(
        br'(?<!'+urlregexps.urlbyte+br')(?:'+
        # Things that look like href= that are not a link to a page:
        # example text that talks about hrefs; <base href="...">.
        # Only <a>, <area> and possibly <link> elements can have
        # hrefs we're interested in.  By excluding not-actually-links,
        # we can have broken-link detection without false positives
        # (or few enough false positives that it's trivial to work around).
        br'''<(?:[Aa]|[Aa][Rr][Ee][Aa]|[Ll][Ii][Nn][Kk])\s[^<>]*href=(?P<quote>["']?)(?P<url1>'''+urlregexps.urlbyte+br'''+)(?<!\?rr)(?P=quote)'''+
        br'''|(?P<url2>'''+urlregexps.urlbyte+br'''+)\?rr'''+
        br')(?!'+urlregexps.urlbyte+br')'
        ,
        contents):
      url = href.group('url1') or href.group('url2')
      linktype = 'rr' if href.group('url2') != None else 'href'
      ref = url.decode('utf-8')
      if linktype == 'rr':
        path = fake_resource_route+normpath(join(dirname(f), ref))
      elif linktype == 'href':
        path = urldefrag(urljoin(route, ref))[0]
      if path in route_metadata:
        result.add(path)
      else:
        # (we don't currently try to check links to third-party websites)
        if path[:len(config.hypothetical_scheme_and_domain)] == config.hypothetical_scheme_and_domain:
          sys.stderr.write(route + ' links to nonexistent ' + ref + '\n')
          nonlocal broken_link_found
          broken_link_found = True
    return result
  for f in config.butdontindexfrom:
    # Double check that butdontindexfrom doesn't have any typoes
    assert(f in route_metadata)
  routes_robots_should_index = set(utils.make_transitive(
      lambda f: filter(lambda f2: f2 not in config.butdontindexfrom, find_internal_links(f)),
    True, True)(config.doindexfrom))
  if broken_link_found:
    exit(1)

  # Auto redirect trailing slashes or lack thereof,
  # regardless of whether there were directories involved in
  # creating the routes.
  for route in nonresource_routes:
    domainless_route = re.sub(urlregexps.urlschemeanddomain, '', route)
    if len(domainless_route) > 1:
      if domainless_route[-1] == '/':
        dual = route[:-1]
      else:
        dual = route+'/'
      domainless_dual = re.sub(urlregexps.urlschemeanddomain, '', dual)
      if dual not in route_metadata:
        if route_metadata[route].status == 301:
          # Avoid pointless double redirect where applicable
          route_metadata[dual] = copy.deepcopy(route_metadata[route])
          route_metadata[dual].http_redirect_to = urljoin(domainless_route, route_metadata[route].http_redirect_to)
        else:
          add_redirect(301, dual, domainless_route)

  for route in route_metadata:
    if urlparse(route).path == '/robots.txt':
      route_metadata[route].headers.append(('Cache-Control', 'max-age=15, must-revalidate'))
    elif is_fake_rr(route) or urlparse(route).path == '/t.gif':
      route_metadata[route].headers.append(("Cache-Control", "max-age=8000000"))
    elif urlparse(route).path == '/favicon.ico':
      route_metadata[route].headers.append(('Cache-Control', 'max-age=400000'))
    else:
      route_metadata[route].headers.append(("Cache-Control", "max-age=300"))
    route_metadata[route].headers.append(("X-Robots-Tag",
      "noarchive" if route in routes_robots_should_index else "noarchive, noindex"))
    route_metadata[route].headers.append(("X-Frame-Options", "SAMEORIGIN"))
    if route_metadata[route].status in {200}:
      # http://googlewebmastercentral.blogspot.com/2011/06/supporting-relcanonical-http-headers.html
      if not is_fake_rr(route):
        canonical_url = route
        route_metadata[route].headers.append(("Link", '<'+canonical_url+'>; rel="canonical"'))
      #rrf = fake_rr_to_f(route)
      #if rrf != None:
      #  # canonical_resources_route similar to nocdn_resources_route or
      #  # config.canonical_scheme_and_domain + config.nocdn_resources_path ?
      #  canonical_url = canonical_resources_route+rewriter.recall_rewritten_resource_name(rrf)
      #else:
      #  canonical_url = route
      #route_metadata[route].headers.append(("Link", '<'+canonical_url+'>; rel="canonical"'))

  utils.write_file_text('nocdn-resource-routes',
    '\n'.join(config.hypothetical_scheme_and_domain + config.nocdn_resources_path #nocdn_resources_route?
                + rewriter.recall_rewritten_resource_name(fake_rr_to_f(f))
              for f in resource_routes))
  utils.write_file_text('nonresource-routes', '\n'.join(nonresource_routes))

  route_metadata[None] = copy.deepcopy(file_metadata['404.html'])
  route_metadata[None].headers.extend([
      ("X-Frame-Options", "SAMEORIGIN"),
      ("X-Robots-Tag", "noarchive, noindex, nosnippet"),
      ])

  #'twould be elegant if each resource can be in a different server...
  #(say, 100MB+ resources get a different server :P)
  #provide  f : old -> (old -> new) -> (new -> old)
  return route_metadata, rewriter


def nginx_openresty(config, do, rewriter, route_metadata):
  rewritten_dir = 'rewritten-towards/nocdn-content-encoding-negotiable'
  rewriter.rewrite(rewritten_dir,
    lambda f, o: config.nocdn_resources_path + f, os.link, os.link)
  # nginx_routes e.g.
  #   {'/foo': 'http://www.idupree.com/foo',
  #    '/_resources/bar.css': 'http://fake-rr.idupree.com/bar.css'
  #   }
  nginx_routes = {}
  for route in route_metadata:
    if route != None:
      rrf = fake_rr_to_f(route)
      if rrf != None:
        nginx_routes[config.nocdn_resources_path+rewriter.recall_rewritten_resource_name(rrf)] = route
      else:
        nginx_routes[re.sub(r'^'+re.escape(config.hypothetical_scheme_and_domain), '', route)] = route
  def recall_nginx_pagecontent_hash(f):
    return utils.read_file_text('nginx-pagecontent-hash/'+f)
  def recall_nginx_pagecontent_path(f, gzipped=False):
    #back from when using .digest() rather than .hexdigest(),
    #h = base64.b16encode(recall_nginx_pagecontent_hash(f)).decode('ascii')
    #Switched to hexdigest() because it's easier to diagnose problems
    #using the shell that way.
    h = recall_nginx_pagecontent_hash(f)
    return h[0:2]+'/'+h[2:60] + ('.gz' if gzipped else '')
  nginx_pagecontent_dir_build = 'nginx/idupreecom/pagecontent/'
  #nginx_pagecontent_dir_deploy = '/srv/openresty/conf/pagecontent/'
  # TODO could make this path include a random secret component
  nginx_pagecontent_url_prefix_deploy = '/pagecontent/'
  #for route in nginx_routes.values():
  for route in route_metadata:
    if route_metadata[route].file != None:
      f = route_metadata[route].file
      worth_gzipping = route_metadata[route].worth_gzipping
      src = join(rewritten_dir, f)
      for [_], [dest] in do([src], ['nginx-pagecontent-hash/'+f]):
        utils.write_file_text(dest, utils.sha384file(src).hexdigest())
      for gz in [True, False] if worth_gzipping else [False]:
        cp_ish = utils.gzip_omitting_metadata if gz else os.link
        for [_], [dest] in do(
            [src],
            [nginx_pagecontent_dir_build+recall_nginx_pagecontent_path(f, gz)]):
            #['nginx/pages/'+('gz/' if gz else 'nogz/')+f]):
          cp_ish(src, dest)
  def make_etag(status, headers, f):
    h = hashlib.sha384()
    # There's probably nothing hidden by adding a random secret here,
    # but it's also harmless.
    h.update(config.nginx_hash_random_bytes)
    h.update(str(status).encode('ascii')+b"\n")
    # (Omit irrelevant auto server headers like "Date:")
    for k, v in headers:
      h.update(k.encode('utf-8')+b": "+v.encode('utf-8')+b"\n")
    if f != None:
      h.update(b"\n")
      # Consistently including page content hashes here is as good
      # as consistently including the page content itself, and faster.
      h.update(recall_nginx_pagecontent_hash(f).encode('ascii'))
    # 22 base64 characters is more than 128 bits,
    # plenty to make collisions implausible
    return base64.urlsafe_b64encode(h.digest())[:22].decode('ascii')
  
  def make_rule(route):
    """f can be none, in which case there is no HTTP body"""
    gzippable = route_metadata[route].worth_gzipping
    http_redirect_to = route_metadata[route].http_redirect_to
    headers = copy.deepcopy(route_metadata[route].headers)
    f = route_metadata[route].file
    status = route_metadata[route].status
    if gzippable:
      headers.append(("Vary", "Accept-Encoding"))
    # estimated_location_headers: more relative than we will serve,
    # because some client or proxy code doesn't like relative Location headers.
    # (Relative Location headers used to be nonstandard.)
    estimated_location_headers = ([("Location", http_redirect_to)] if http_redirect_to != None else [])
    etag_nogz = make_etag(status, estimated_location_headers + headers, f)
    etag_gz = make_etag(status, estimated_location_headers + headers + [("Content-Encoding", "gzip")], f)
    def make_headers(indent):
      """
      adds nginx code to print all the non Content-Encoding:gzip headers
      """
      # most headers:
      for k, v in headers:
        rule.append(indent+"""ngx.header[{k}]={v}""".format(k=repr(k), v=repr(v)))
      # Location header, if any:
      if http_redirect_to != None:
        # ngx.redirect() doesn't support path-relative or protocol-relative
        # redirect destinations, and forces its own default response body,
        # so I'm not using it.
        if re.search(urlregexps.absoluteurl, http_redirect_to):
          expr = repr(http_redirect_to)
        elif re.search(urlregexps.protocolrelativeurl, http_redirect_to):
          expr = """ngx.var.scheme..{}""".format(repr(':'+http_redirect_to))
        else:
          domainrelative_redirect_to = re.sub(urlregexps.urlschemeanddomain, '',
                                              urljoin(route, http_redirect_to))
          expr = ("""ngx.var.scheme..'://'..ngx.var.host..port_string()..{}"""
                   .format(repr(domainrelative_redirect_to)))
        rule.append(indent+"""ngx.header[{k}]={v}""".format(k=repr('Location'), v=expr))
    # Python and Lua string syntaxes are similar enough that we can use
    # Python repr() to make Lua strings. 
    rule = ["function()"]
    if f != None and status != 200:
      # nginx seems to reset the status to 200 upon ngx.exec(),
      # so give up on doing fancy stuff rather than try subrequests with
      # "Certain Lua APIs provided by ngx_lua do not work in Nginx's SPDY mode
      # yet: ngx.location.capture, ngx.location.capture_multi, and ngx.req.socket."
      contents = utils.read_file_binary(
        nginx_pagecontent_dir_build+recall_nginx_pagecontent_path(f))
      rule.append("""  ngx.status={status}""".format(status=status))
      make_headers('  ')
      rule.append("  ngx.print({})".format(repr(contents)[1:]))
    else:
      if f != None:
        fpath = nginx_pagecontent_url_prefix_deploy+recall_nginx_pagecontent_path(f)
        if gzippable:
          fpath_gz = nginx_pagecontent_url_prefix_deploy+recall_nginx_pagecontent_path(f, True)
          rule.append("""  local gzip = accept_encoding_gzip(); local fpath, etag""")
          rule.append("""  if gzip then fpath = {fpath_gz}; etag = {etag_gz}"""
            .format(fpath_gz=repr(fpath_gz), etag_gz=repr(etag_gz)))
          rule.append("""  else fpath = {fpath_nogz}; etag = {etag_nogz}"""
            .format(fpath_nogz=repr(fpath), etag_nogz=repr(etag_nogz)))
          rule.append("""  end""")
        else:
          rule.append("""  local fpath = {fpath}; local etag = {etag}"""
            .format(fpath=repr(fpath), etag=repr(etag_nogz)))
        rule.append("""  ngx.header['ETag'] = etag""")
        rule.append("""  if ngx.var.http_if_none_match == etag then ngx.status = 304 else""")
      rule.append("""    ngx.status={status}""".format(status=status))
      if gzippable:
        rule.append("""    if gzip then ngx.header['Content-Encoding']='gzip' end""")
      make_headers('    ')
      if f != None:
        rule.append("""    ngx.exec(fpath)""")
        rule.append("""  end""")
    rule.append("""end""")
    return "\n  ".join(rule)

  rules = []
  for nginx_route, route in nginx_routes.items():
    rules.append(
      "[{route}] = {rule},".format(route=repr(nginx_route), rule = make_rule(route)))

  s404 = make_rule(None)

  init_lua = (
  """
  local function accept_encoding_gzip()
    -- This is somewhat incorrect, but I haven't found how to use nginx's
    -- Accept-Encoding parser here, and getting it right doesn't seem
    -- useful enough to write a Lua "Accept-Encoding:" parser myself here.
    local accept_encoding = ngx.var.http_accept_encoding
    return (accept_encoding ~= nil) and
           (ngx.re.match(accept_encoding, 'gzip', 'o') ~= nil)
  end
  local function port_string()
    local scheme = ngx.var.scheme
    local port = ngx.var.server_port
    if (scheme == 'http' and port == '80') or (scheme == 'https' and port == '443')
    then return ''
    else return ':'..port
    end
  end
  """ +
  "local pages = {\n" + "\n".join(rules) + "\n}\n" +
  "local s404 = " + s404 + "\n" +
  "local function do_page(path) (pages[path] or s404)(path) end\n" +
  "return do_page\n"
  )
  
  utils.write_file_text('nginx/idupreecom/do_page.lua', init_lua)
  #for [src], [dest] in do(['src/aux/nginx.conf'], ['nginx/nginx.conf']):
  #  os.link(src, dest)

    
if __name__ == '__main__':
  build()
