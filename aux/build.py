
import os, os.path, subprocess, re, base64, hashlib, mimetypes
from os.path import join, exists, dirname, relpath

import buildsystem, utils
import errdocs, htaccess
import urlregexps
import myglob
import resource_rewriting
import secrets

cmd = subprocess.check_call

nocdn_resources_path = '/_resources/'
cdn_resources_path = '//??????????.cloudfront.net/'

def convert_path_to_domainrelative_urlpath(p):
  assert(p[0] != '/')
  return '/' + os.path.normpath(p)

def build():
  os.chdir(os.path.dirname(os.path.join('.', __file__)))
  os.chdir('..')
  for do in buildsystem.run('.',
        set(myglob.fglob('aux/**.py'))|set(myglob.fglob('priv/**.py'))):
    
    # TODO in tests, test that files_to_gzip and not others
    # are gzipped when Accept-Encoding gzip and are Vary and
    # that the other headers exist too.
    routes, files_to_gzip, file_headers, rewriter = \
        custom_site_preprocessing(do)

    nginx_openresty(do, rewriter, routes, files_to_gzip, file_headers)

    httpd_possibly_along_with_cdn_incapable_of_gz_negotiation(do, rewriter, routes, files_to_gzip, file_headers)
    

def custom_site_preprocessing(do):
  """
  Returns routes, files_to_gzip, file_headers

  Creates 'site/' from 'src/site/' and some custom rules.

  do : from buildsystem.py
  routes : dict from site-relative URL paths to source file paths.
  files_to_gzip : set of source file paths that are worth being served gzipped.
  files_robots_should_index : set of source file paths that we want to let
    Google et al. index.
  files_to_rewrite : files that have resource-rewritable links in them
  file_headers : function from source file path to list of pairs (name, value)
    of HTTP headers specially for that route (e.g. Content-Type)
  """
  # The following are the path without any src/site/ or site/ prefix.
  # (Hmm, why *don't* the auxiliary dirs all have site/ under them in paths?
  #  It would mean less add/removing of path components.)
  files_to_consider = list(utils.relpath_files_under('src/site'))
  files_to_rewrite = set()
  files_to_gzip = set()  #superset of files_to_rewrite; see [Note_Superset]
  # routes: Association from paths on the main site to file paths.
  # Used for setting rel=canonical and for sorting files into the right places.
  # It's a bidirectional association:
  #   routes is {route: file}
  #   reverse_routes is {file: route}
  # In {route: file} format although it is really a bidirectional association.
  routes = {}
  reverse_routes = {}
  # file_headers_dict is {file: list of HTTP headers in k,v pair form}
  # We could change from file_headers_dict to route_headers_dict if we make
  # the routes dict include resources, although that would make this function
  # more twisty to do everything in the correct order.
  file_headers_dict = {}
  #potential_site_files = set()

  def add_route(route, f):
    assert(route not in routes)
    routes[route] = f
    reverse_routes[f] = route

  # TODO let resources be on a CDN with a different path
  scheme_and_domain = 'http://www.idupree.com'

  def autohead(src, dest, canonical_url):
    #utils.file_re_sub(src, dest, b'{{:canonical}}', url.encode('utf-8'))
    # TODO test/allow alternate explicit icons.
    # My browsers don't fetch '/favicon.ico' at all.
    utils.file_re_sub(src, dest, br'((?:\n|^)[ \t]*)<!--AUTOHEAD-->',
      br'\1<link rel="canonical" href="' + canonical_url.encode('utf-8') + b'" />' +
      br'\1<link rel="shortcut icon" href="/favicon.ico?rr" />'
      )

  def intuit_from_destf(destf):
    # I can add exceptions to these whenever I want to.
    if re.search(r'\.(html|css|js|svg)$', destf):
      files_to_gzip.add(destf)
    if re.search(r'\.(html|css|js)$', destf):
      files_to_rewrite.add(destf)
      # [Note_Superset]
      # (Relevant for deployments that put resources on a static content
      #  server that can't content-negotiate gzip-encoding.)
      #
      # It's easiest to gzip all rewritten files, because their resources
      # might also need to be gzipped-when-client-supports-it, and since
      # it makes deployment slightly simpler and almost all files with
      # links in them will benefit from gzipping.
      assert(destf in files_to_gzip)
    mime, content = mimetypes.guess_type(destf)
    if content != None or mime == None:
      mime = 'application/octet-stream'
    if re.search('^text/|[+/](?:xml|json)$|^application/javascript$', mime):
      mime += '; charset=utf-8'
    file_headers_dict[destf] = [('Content-Type', mime)]
    #potential_site_files.add(destf)
    
  for f in files_to_consider:
    src = join('src/site', f)
    route = None
    if re.search(r'\.(html|md)$', f):
      is_markdown = re.search(r'\.md$', f)
      extless_path = re.sub(r'\.(html|md)$', '', f)
      destf = extless_path+'.html'
      dest = join('site', destf)
      # slight hack for index.html file
      route = re.sub('/index$', '/', convert_path_to_domainrelative_urlpath(extless_path))
      url = scheme_and_domain+route
      add_route(route, destf)
      if is_markdown:
        for [_, templ], [_] in do([src, 'src/aux/pandoc-template.html'], [dest]):
          cmd(['pandoc', '--template='+templ, '-t', 'html5', '-o', dest, src])
          autohead(dest, dest, url)
      else:
        for _ in do([src], [dest]):
          autohead(src, dest, url)
    elif re.search(r'\.(txt)$|^t\.gif$', f):
      destf = f
      route = convert_path_to_domainrelative_urlpath(f)
      add_route(route, destf)
      dest = join('site', f)
      for _ in do([src], [dest]):
        os.link(src, dest)
    else:
      destf = f
      dest = join('site', f)
      for _ in do([src], [dest]):
        os.link(src, dest)
    intuit_from_destf(destf)

  def svg_to_png(src, dest, width, height):
    cmd(['inkscape', '--without-gui', '--export-png='+dest,
      '--export-background-opacity=0', '-w', str(width), '-h', str(height),
      str(src)])
    cmd(['optipng', dest])

  destf = 'nabla.png'
  for [src], [dest] in do(['src/site/favicon.svg'], [join('site', destf)]):
    svg_to_png(src, dest, 64, 64)
  intuit_from_destf(destf)

  for destf, xy in [('favicon16x16.png', 16), ('favicon32x32.png', 32)]:
    for [src], [dest] in do(['src/site/favicon.svg'], [join('site', destf)]):
     svg_to_png(src, dest, xy, xy)

  destf = 'favicon.ico'
  for srcs, [dest] in do(['site/favicon16x16.png'],#, 'site/favicon32x32.png'],
                         [join('site', destf)]):
    cmd(['convert'] + srcs + [dest])
  #file_headers_dict[destf] = [('Content-Type', 'image/png')]
  intuit_from_destf(destf)
  route = convert_path_to_domainrelative_urlpath(destf)
  add_route(route, destf)

  #TODO use do() to make this cached in a file.
  def find_internal_links(f):
    """
    Given a file path f, returns (an estimate of) all file paths that
    it links to in any manner (href or resource).  Won't find links
    that are neither in an "href" nor marked as a rewritable-resource link
    (erring on the side of not finding links since finding links risks
    half-private pages being Google-indexable, while finding no links
    in weird cases just means weird enough things won't be Google-indexable
    unless I explicitly mark them into that list).
    """
    result = set()
    # TODO if we except some HTML files from rewriting then this
    # will be wrong:
    if f not in files_to_rewrite:
      return result
    contents = utils.read_file_binary(join('site', f))
    for href in re.finditer(
        br'(?<!'+urlregexps.urlbyte+br')(?:'+
        br'''href=(?P<quote>["']?)(?P<url1>'''+urlregexps.urlchar+br'''+)(?<!\?rr)(?P=quote)'''+
        br'''|(?P<url2>'''+urlregexps.urlchar+br'''+)\?rr'''+
        br')(?!'+urlregexps.urlbyte+br')'
        ,
        contents):
      url = href.group('url1') or href.group('url2')
      linktype = 'rr' if href.group('url2') != None else 'href'
      if not re.search(urlregexps.urlwithdomain, url):
        ref = re.search(br'^[^?#]*', url).group().decode('utf-8')
        if len(ref) > 0:
          if linktype == 'rr':
            result.add(join(dirname(f), ref))
          elif linktype == 'href':
            if ref[0] == '/':
              path = ref
            else:
              path = join(dirname(reverse_routes[f]), ref)
            if path in routes:
              result.add(routes[path])
    return result
  doindexfrom = map(lambda p: routes[p], ['/'])
  butdontindexfrom = map(lambda p: routes[p], ['/README'])
  files_robots_should_index = set(utils.make_transitive(
      lambda f: filter(lambda f2: f2 not in butdontindexfrom, find_internal_links(f)),
    True, True)(doindexfrom))
  
  # It's not super elegant calling the rewriter inside custom processing
  # rather than after, but it'll do.
  rewriter = resource_rewriting.ResourceRewriter(do, files_to_rewrite,
                              site_source_prefix = 'site')

  site_files = set(reverse_routes) | rewriter.recall_all_needed_resources()
  for f in site_files:
    if f in reverse_routes and reverse_routes[f] != '/t.gif':
      if reverse_routes[f] == '/robots.txt':
        file_headers_dict[f].append(('Cache-Control', 'max-age=15, must-revalidate'))
      else:
        file_headers_dict[f].append(("Cache-Control", "max-age=300"))
    else:
      file_headers_dict[f].append(("Cache-Control", "max-age=8000000"))
    file_headers_dict[f].append(("X-Robots-Tag",
      "noarchive" if f in files_robots_should_index else "noarchive, noindex"))
    file_headers_dict[f].append(("X-Frame-Options", "SAMEORIGIN"))
    # http://googlewebmastercentral.blogspot.com/2011/06/supporting-relcanonical-http-headers.html
    canonical_url = ((scheme_and_domain+reverse_routes[f]) if f in reverse_routes else
      (scheme_and_domain+nocdn_resources_path+rewriter.recall_rewritten_resource_name(f)))
    file_headers_dict[f].append(("Link", '<'+canonical_url+'>; rel="canonical"'))

  utils.write_file_text('nocdn-resource-routes',
    '\n'.join(nocdn_resources_path+rewriter.recall_rewritten_resource_name(f)
              for f in rewriter.recall_all_needed_resources()))
  utils.write_file_text('nonresource-routes', '\n'.join(routes))

  def file_headers(f):
    if f in file_headers_dict:
      return file_headers_dict[f]
    else: return [
      ("X-Frame-Options", "SAMEORIGIN"),
      ("X-Robots-Tag", "noarchive, noindex")
      ]

  return routes, files_to_gzip, file_headers, rewriter

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


def nginx_openresty(do, rewriter, routes, files_to_gzip, file_headers):
  rewritten_dir = 'rewritten-towards/nocdn-content-encoding-negotiable'
  rewriter.rewrite(rewritten_dir,
    lambda f, o: nocdn_resources_path + f, os.link, os.link)
  nginx_resource_routes = {
      nocdn_resources_path+rewriter.recall_rewritten_resource_name(r): r
      for r in rewriter.recall_all_needed_resources()
    }
  nginx_routes = {}
  nginx_routes.update(routes)
  nginx_routes.update(nginx_resource_routes)
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
  for route, f in nginx_routes.items():
    src = join(rewritten_dir, f)
    for [_], [dest] in do([src], ['nginx-pagecontent-hash/'+f]):
      utils.write_file_text(dest, utils.sha384file(src).hexdigest())
    for gz in [True, False] if f in files_to_gzip else [False]:
      cp_ish = utils.gzip_omitting_metadata if gz else os.link
      for [_], [dest] in do(
          [src],
          [nginx_pagecontent_dir_build+recall_nginx_pagecontent_path(f, gz)]):
          #['nginx/pages/'+('gz/' if gz else 'nogz/')+f]):
        cp_ish(src, dest)
  def make_etag(headers, f):
    h = hashlib.sha384()
    # There's probably nothing hidden by adding a random secret here,
    # but it's also harmless.
    h.update(secrets.nginx_hash_random_bytes)
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
  
  def make_rule(status, f, route):
    """f can be none, in which case there is no HTTP body"""
    headers = []
    gzippable = f in files_to_gzip
    headers += file_headers(f)
    if gzippable:
      headers.append(("Vary", "Accept-Encoding"))
    etag_nogz = make_etag(headers, f)
    etag_gz = make_etag(headers + [("Content-Encoding", "gzip")], f)
    # Python and Lua string syntaxes are similar enough that we can use
    # Python repr() to make Lua strings. 
    rule = ["function()"]
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
  for route, f in nginx_routes.items():
    rules.append(
      "[{route}] = {rule},".format(route=repr(route), rule = make_rule(200, f, route)))

  #s404 = make_rule(404, None, None)
  s404 = "\n  ".join(["function()", "  ngx.status=404"] +
    ["  ngx.header[{k}]={v}".format(k=repr(k), v=repr(v))
     for k, v in file_headers(None)] +
    ["  ngx.print({})".format(repr(errdocs.errdoc(404))), "end"])

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
