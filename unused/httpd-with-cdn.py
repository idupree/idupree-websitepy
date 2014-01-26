

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