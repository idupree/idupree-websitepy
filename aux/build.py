
import os, os.path, subprocess, re, base64, hashlib, mimetypes, copy
from os.path import join, dirname, normpath, exists
from urllib.parse import urljoin, urldefrag, urlparse

import buildsystem, utils
import errdocs, htaccess
import urlregexps
import myglob
import resource_rewriting
import secrets
from private_configuration import cdn_resources_path, scheme_and_domain, doindexfrom, butdontindexfrom

cmd = subprocess.check_call

nocdn_resources_path = '/_resources/'
#cdn_resources_path = '//??????????.cloudfront.net/'

#scheme_and_domain = 'http://www.idupree.com'
nocdn_resources_route = scheme_and_domain+nocdn_resources_path
canonical_resources_route = nocdn_resources_route

#doindexfrom = map(lambda r: scheme_and_domain+r, ['/'])
#butdontindexfrom = map(lambda r: scheme_and_domain+r, ['/semiprivate-page'])

# fake_resource_route: prefixed to resource names to give them
# routes before they are rewritten to the actual resource-route prefix
# and contents-hash.
fake_resource_route = 'http://fake-rr.idupree.com/'
def is_fake_rr(route):
  return route[:len(fake_resource_route)] == fake_resource_route
def fake_rr_to_f(route):
  if is_fake_rr(route): return route[len(fake_resource_route):]
  else: return None


def build():
  os.chdir(os.path.dirname(os.path.join('.', __file__)))
  os.chdir('..')
  for do in buildsystem.run('.',
        set(myglob.fglob('aux/**.py'))|set(myglob.fglob('priv/**.py'))):
    
    # TODO in tests, test that files_to_gzip and not others
    # are gzipped when Accept-Encoding gzip and are Vary and
    # that the other headers exist too.
    route_metadata, rewriter = \
        custom_site_preprocessing(do)

    nginx_openresty(do, rewriter, route_metadata)

#    httpd_possibly_along_with_cdn_incapable_of_gz_negotiation(do, rewriter, routes, files_to_gzip, file_headers)
    
class RouteInfo(object):
  """
  status: numeric HTTP status code
  headers: list of pairs of str (header name, header value)
  file: 'site/'-relative path to a file containing the HTTP body
    for responding to this request, or None for no body
  worth_gzipping: whether to Vary:Accept-Encoding this
  """
  def __init__(self, status = None, headers = None, file = None, worth_gzipping = None):
    self.status = status
    self.headers = headers if headers != None else []
    self.file = file
    self.worth_gzipping = worth_gzipping
#and have a base one provided by f's that is copy+added to by specific routes

def custom_site_preprocessing(do):
  """
  Returns route_metadata, rewriter

  Creates 'site/' from 'src/site/' and some custom rules.

  do : from buildsystem.py
  route_metadata : dict from URL string to RouteInfo.
  rewriter : resource_rewriting.ResourceRewriter
  """
  # The following are the path without any src/site/ or site/ prefix.
  # (Hmm, why *don't* the auxiliary dirs all have site/ under them in paths?
  #  It would mean less add/removing of path components.)
  files_to_consider = list(utils.relpath_files_under('src/site'))
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

  def autohead(src, dest, canonical_url):
    #utils.file_re_sub(src, dest, b'{{:canonical}}', url.encode('utf-8'))
    # TODO test/allow alternate explicit icons.
    # My browsers don't fetch '/favicon.ico' at all.
    utils.file_re_sub(src, dest, br'((?:\n|^)[ \t]*)<!--AUTOHEAD-->',
      br'\1<link rel="canonical" href="' + canonical_url.encode('utf-8') + b'" />' +
      br'\1<link rel="shortcut icon" href="/favicon.ico?rr" />'
      )

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
      bool(re.search(r'\.(html|css|js|svg)$', f))
    if re.search(r'\.(html|css|js)$', f):
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
      else:
        mime, content = mimetypes.guess_type(f)
        if content != None or mime == None:
          mime = 'application/octet-stream'
      if re.search('^text/|[+/](?:xml|json)$|^application/javascript$', mime):
        mime += '; charset=utf-8'
      file_metadata[f].headers.append(('Content-Type', mime))

  def add_redirect(status, from_route, to_route):
    add_route(from_route)
    route_metadata[from_route].status = status
    route_metadata[from_route].headers.append((
        'Location', urljoin(from_route, to_route)))

  for srcf in files_to_consider:
    src = join('src/site', srcf)
    route = None
    f = None
    if re.search(r'\.(html|md)$', srcf):
      is_markdown = re.search(r'\.md$', srcf)
      extless_path = re.sub(r'\.(html|md)$', '', srcf)
      f = extless_path+'.html'
      dest = join('site', f)
      # slight hack for index.html file
      route = re.sub('/index$', '/', scheme_and_domain+'/'+extless_path)
      url = route
      if is_markdown:
        for [_, templ], [_] in do([src, 'src/aux/pandoc-template.html'], [dest]):
          cmd(['pandoc', '--template='+templ, '-t', 'html5', '-o', dest, src])
          autohead(dest, dest, url)
      else:
        for _ in do([src], [dest]):
          autohead(src, dest, url)
    elif re.search(r'\.(scss|sass)$', srcf):
      f = re.sub(r'\.(scss|sass)$', '.css', srcf)
      # don't disturb precompiled scss:
      if exists(join('src/site', f)):
        f = None
      else:
        f_map = f+'.map'
        dest = join('site', f)
        #I don't have a scss dependency chaser, so I can't easily give
        #the correct set of dependencies to do(), but sassc is pretty fast
        #so I'll run it every time.
        # Creates both f and f_map:
        cmd(['sassc', '-g', '-o', dest, src])
    elif re.search(r'\.(txt|asc|pdf|tar\.(gz|bz2|xz))$|^t\.gif$|^haddock-presentation-2010/', srcf):
      f = srcf
      route = scheme_and_domain+'/'+f
      dest = join('site', f)
      for _ in do([src], [dest]):
        os.link(src, dest)
    elif re.search(r'\.(3[0-9][0-9])$', srcf):
      extless_path = re.sub(r'\.(3[0-9][0-9])$', '', srcf)
      # Hmm should 'index.301' be a thing? or '.301'? or just use dirname.301
      route = scheme_and_domain+'/'+extless_path
      # Alas, this code currently can't support redirecting to a resource.
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

  def svg_to_png(src, dest, width, height):
    cmd(['inkscape', '--without-gui', '--export-png='+dest,
      '--export-background-opacity=0', '-w', str(width), '-h', str(height),
      str(src)])
    cmd(['optipng', dest])

  f = 'nabla.png'
  for [src], [dest] in do(['src/site/favicon.svg'], [join('site', f)]):
    svg_to_png(src, dest, 64, 64)
  add_file(f)

  for f, xy in [('favicon16x16.png', 16), ('favicon32x32.png', 32)]:
    for [src], [dest] in do(['src/site/favicon.svg'], [join('site', f)]):
     svg_to_png(src, dest, xy, xy)

  f = 'favicon.ico'
  for srcs, [dest] in do(['site/favicon16x16.png'],#, 'site/favicon32x32.png'],
                         [join('site', f)]):
    cmd(['convert'] + srcs + [dest])
  # IE < 11 needs favicon to be ico format
  add_file(f)
  route = scheme_and_domain+'/'+f
  add_route(route, f)

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
        br'''href=(?P<quote>["']?)(?P<url1>'''+urlregexps.urlbyte+br'''+)(?<!\?rr)(?P=quote)'''+
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
    return result
  routes_robots_should_index = set(utils.make_transitive(
      lambda f: filter(lambda f2: f2 not in butdontindexfrom, find_internal_links(f)),
    True, True)(doindexfrom))
  
  # It's not super elegant calling the rewriter inside custom processing
  # rather than after, but it'll do.
  rewriter = resource_rewriting.ResourceRewriter(
    files_to_rewrite, site_source_prefix = 'site', do=do)

  nonresource_routes = [route_ for route_ in route_metadata]

  # Auto redirect trailing slashes or lack thereof,
  # regardless of whether there were directories involved in
  # creating the routes.
  for route in nonresource_routes:
    if len(route) > 1:
      if route[-1] == '/':
        dual = route[:-1]
      else:
        dual = route+'/'
      if dual not in route_metadata:
        if route_metadata[route].status == 301:
          # Avoid pointless double redirect where applicable
          route_metadata[dual] = copy.deepcopy(route_metadata[route])
        else:
          add_redirect(301, dual, route)

  for f in rewriter.recall_all_needed_resources():
    add_route(fake_resource_route+f, f)

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
      rrf = fake_rr_to_f(route)
      if rrf != None:
        canonical_url = canonical_resources_route+rewriter.recall_rewritten_resource_name(rrf)
      else:
        canonical_url = route
      route_metadata[route].headers.append(("Link", '<'+canonical_url+'>; rel="canonical"'))

  utils.write_file_text('nocdn-resource-routes',
    '\n'.join(nocdn_resources_route+rewriter.recall_rewritten_resource_name(f)
              for f in rewriter.recall_all_needed_resources()))
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

def httpd_possibly_along_with_cdn_incapable_of_gz_negotiation(do, rewriter, routes, files_to_gzip, file_headers):
  """
  Warning: this may be more broken and/or out of date than the nginx-openresty
  deployment method, because I'm not using it and it's more difficult to make
  it do exactly the things I want.
  """
  #TODO use file_headers

  # A "bug" is that any file that includes resources that should be
  # served gzipped must, itself, be gzipped.  However, this simplifies
  # deployment, and in practice nearly all files with textual links in them
  # are compressible.
  def gzstr(gz): return 'gz/' if gz else 'n/' #or, nogz/ ?
  rewritings = (
    ('rewritten-towards/nocdn-nogz',
        lambda f, o: nocdn_resources_path + gzstr(False)              + f),
    ('rewritten-towards/nocdn-gz',
        lambda f, o: nocdn_resources_path + gzstr(o in files_to_gzip) + f),
    ('rewritten-towards/withcdn-nogz',
        lambda f, o:   cdn_resources_path + gzstr(False)              + f),
    ('rewritten-towards/withcdn-gz',
        lambda f, o:   cdn_resources_path + gzstr(o in files_to_gzip) + f))
  for dest_dir, resource_url_maker in rewritings:
    rewriter.rewrite(dest_dir, resource_url_maker, os.link, os.link)
  #needed_resources = rewriter.recall_all_needed_resources()
  #for f in routes.values():
  #  needed_resources.update(rewriter.recall_transitive_deps(f))
  for whatcdn in 'nocdn', 'withcdn':
    resourcesdir = whatcdn + '/' + ('resources/' if (whatcdn == 'withcdn') else 'pages'+nocdn_resources_path)
    for gz in True, False:
      rewrittendir = 'rewritten-towards/' + whatcdn + ('-gz' if gz else '-nogz')
      cp_ish = utils.gzip_omitting_metadata if gz else os.link
      #pagefile = lambda f: join(whatcdn, 'pages', (f if gz else re.sub(r'(?<=[^/])((?:\.[a-zA-Z0-9]+)*)$', r'.notgzipped\1', f)))
      pagefile = lambda f: join(whatcdn, 'pages', (f if not gz else re.sub(r'(?<=[^/])((?:\.[a-zA-Z0-9]+)*)$', r'\1.gzipped', f)))
      resourcesdirgz = resourcesdir + gzstr(gz)
      cdnfile = lambda f: resourcesdirgz + rewriter.recall_rewritten_resource_name(f)
      for files, destfn in (
            (routes.values(), pagefile),
            (rewriter.recall_all_needed_resources(), cdnfile)):
        for f in files:
          if not gz or f in files_to_gzip:
            for [src], [dest] in do(
                [join(rewrittendir, f)],
                [destfn(f)]):
              cp_ish(src, dest)
    for err in errdocs.errdocErrs:
      for [], [dest] in do([], [join(whatcdn, 'pages',
            'err-'+secrets.errdocs_random_string, str(err.code)+'.htm')]):
        utils.write_file_text(dest, errdocs.errdoc(err))
    for [], [dest] in do([], [join(whatcdn, 'pages', '.htaccess')]):
      utils.write_file_text(dest, htaccess.htaccess)
  for [], [dest] in do([], ['nocdn/pages'+nocdn_resources_path+'.htaccess']):
    utils.write_file_text(dest, """
ExpiresActive On
ExpiresDefault "access plus 33 days"
""")
  for [], [dest] in do([], ['nocdn/pages'+nocdn_resources_path+'gz/.htaccess']):
    utils.write_file_text(dest, """
Header append Content-Encoding gzip
""")


def nginx_openresty(do, rewriter, route_metadata):
  rewritten_dir = 'rewritten-towards/nocdn-content-encoding-negotiable'
  rewriter.rewrite(rewritten_dir,
    lambda f, o: nocdn_resources_path + f, os.link, os.link)
  # nginx_routes e.g.
  #   {'/foo': 'http://www.idupree.com/foo',
  #    '/_resources/bar.css': 'http://fake-rr.idupree.com/bar.css'
  #   }
  nginx_routes = {}
  for route in route_metadata:
    if route != None:
      rrf = fake_rr_to_f(route)
      if rrf != None:
        nginx_routes[nocdn_resources_path+rewriter.recall_rewritten_resource_name(rrf)] = route
      else:
        nginx_routes[re.sub(r'^'+re.escape(scheme_and_domain), '', route)] = route
  def recall_nginx_pagecontent_hash(f):
    return utils.read_file_text('nginx-pagecontent-hash/'+f)
  def recall_nginx_pagecontent_path(f, gzipped=False):
    #back from when using .digest() rather than .hexdigest(),
    #h = base64.b16encode(recall_nginx_pagecontent_hash(f)).decode('ascii')
    #Switched to hexdigest() because it's easier to diagnose problems
    #using the shell that way.
    h = recall_nginx_pagecontent_hash(f)
    return h[0:2]+'/'+h[2:60] + ('.gz' if gzipped else '')
  nginx_pagecontent_dir_build = 'nginx/pagecontent/'
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
    h.update(secrets.nginx_hash_random_bytes)
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
    headers = copy.deepcopy(route_metadata[route].headers)
    f = route_metadata[route].file
    status = route_metadata[route].status
    if gzippable:
      headers.append(("Vary", "Accept-Encoding"))
    etag_nogz = make_etag(status, headers, f)
    etag_gz = make_etag(status, headers + [("Content-Encoding", "gzip")], f)
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
      for k, v in headers:
        rule.append("""  ngx.header[{k}]={v}""".format(k=repr(k), v=repr(v)))
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
      for k, v in headers:
        rule.append("""    ngx.header[{k}]={v}""".format(k=repr(k), v=repr(v)))
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
  """ +
  "local pages = {\n" + "\n".join(rules) + "\n}\n" +
  "local s404 = " + s404 + "\n" +
  "function do_page(path) (pages[path] or s404)(path) end\n"
  )
  
  utils.write_file_text('nginx/init.lua', init_lua)
  for [src], [dest] in do(['src/aux/nginx.conf'], ['nginx/nginx.conf']):
    os.link(src, dest)

    
if __name__ == '__main__':
  build()
