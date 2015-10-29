
import textwrap, re

def normtext(block):
  """
  makes a block of text have no unnecessary indentation,
  begin with a non-newline,
  and end with a newline
  """
  return textwrap.dedent(block).strip('\n') + '\n'

def neighbors(*blocks):
  return '\n'.join(normtext(b) for b in blocks)

def wrapped(wrapper, *blocks):
  """
  Example:

  wrapped('http', '''
                     foo {
                         bar;
                     }
                  ''')

    -->

  '''http {\n    foo {\n        bar;\n    }\n}\n'''
  """
  #return (textwrap.dedent(wrapped).strip('\n') + ' {\n' +
  return (wrapper + ' {\n' +
    textwrap.indent(neighbors(*blocks), '    ') +
    '}\n')


def _make_nginx_less_fancy_for_the_sake_of_our_lua_code():
  return normtext('''
    # We use some of nginx's filesystem-file serving because it
    # supports byte-range requests, which are a bit nontrivial.
    # However:

    # Lua always specifies the Content-Type
    lua_use_default_type off;

    # We handle our own ETags.
    etag off;

    # Disable If-Modified-Since since we have hash-based ETags instead
    if_modified_since off;
    add_header Last-Modified '';
''')

# TODO: is this correct?? I can't find documentation of
# nginx's exact string syntax.
def escape_for_nginx_string(s):
  return re.sub(
    r'''([\\'"])''',
    (lambda m: '\\' + m.group(1)),
    s)

# This only works for lua strings delimited by ' or ".
# Lua strings can also be delimited by [===[...]===]
# for 0+ equals signs, but these strings do not implement
# escaping (similarly to python raw strings) so this
# function cannot work for them.
def escape_for_lua_string(s):
  return re.sub(
    r'''([\\'"])''',
    (lambda m: '\\' + m.group(1)),
    s)


#TODO pagecontent -> idupree_websitepy_pagecontent
# also note that it depends on the lua having the right pagecontent_location
# -- unless I were to pass it to the lua at runtime for no good reason --
# so it's a little odd to specify it here. Commenting that argument out...
def nginx_conf_snippet_for_server_context(
      *,
      # This path unfortunately has to depend on how you set
      # lua_package_path in the http{} section of the nginx config.
      # For example
      #    lua_package_path "/srv/openresty/conf/?.lua";
      # and
      #    lua_path = "idupreecom/data/do_page"
      # combine to find /srv/openresty/conf/idupreecom/data/do_page.lua
      lua_path,
      # pagecontent_path is an absolute file path, or relative to the
      # nginx prefix you'll be using.
      pagecontent_path,
      # 'location' as in the nginx location block argument
      location = '/'
      # This isn't actually configurable:
      #pagecontent_location = '/pagecontent/'
      ):
  pagecontent_location = '/pagecontent/'
  return neighbors(
    wrapped('location "' + escape_for_nginx_string(location) + '"',
      _make_nginx_less_fancy_for_the_sake_of_our_lua_code(),
      '''
      content_by_lua '
        local do_page = require "'''+escape_for_nginx_string(escape_for_lua_string(lua_path))+'''"
        do_page(ngx.var.uri)
        ';
      '''),
    wrapped('location "' + escape_for_nginx_string(pagecontent_location) + '"',
      _make_nginx_less_fancy_for_the_sake_of_our_lua_code(),
      '''
      internal;
      alias "'''+escape_for_nginx_string(pagecontent_path)+'''";
      '''))

