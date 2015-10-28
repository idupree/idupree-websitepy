
# -*- coding: utf-8 -*-
import sys, os, re, html, urllib
from os.path import join, normpath, dirname, basename, isdir, exists

from . import urlregexps
from . import utils
from . import localwebfn

usage = """
Usage:
./aux/rrify.py path/to/dir/to/swizzle/

This swizzling looks for links that might be resource refs
and offers (via web browser UI) to mark them with ?rr and the
proper quotes for you.  It also lets you undo that transformation.
It doesn't make any changes until you submit the web form.
"""

# TODO consider sourceMappingURL.
# Note &amp; and %encoded and \'escaped URL strings may be missed by this code.
# %encoding might be a TODO to decode to find what it points to, at least
# if the rr code can deal with that or if I add .html conversion.
# TODO have /... links be interpretable.


queryandfragment_re = re.compile(r'[?#].*')
nonrelativeurl_re = re.compile(urlregexps.urlwithdomain+'|'+urlregexps.domainrelativeurl)
def url_file_exists(url, filedirname, existence):
  ret = False
  plainurl = re.sub(queryandfragment_re, '', url)
  # "", ".", ".." occur too often as non-URL-related strings and are very
  # likely not files/directories we want to refer to as resources.
  # (On occasion, "." might be wanted, but "./" *is* detected and is
  # at least as likely to be the used string.)
  if not re.search(nonrelativeurl_re, url) and plainurl not in {'', '.', '..'}:
    path = normpath(join(filedirname, plainurl))
    ret = (path in existence)
    # If directory refs would have to end in /:
    # ... and (existence[path] == True or plainurl[-1:] == '/' or url[-3:] == '?rr'))
  return ret

def swizzle_file(display_filename, base_relative_filename, cwd_relative_filename, filecontents, existence):
  """
  returns (an HTML snippet for the file, a dict of transformations that could be applied)
  (see swizzle())
  DONE contain filename and its links to the directory under analysis somehow
  perhaps withwith efficiency by full scanning the dir and listing its files beforehand
  """
  lines = filecontents.decode().splitlines(True)
  filedirname = normpath(dirname(base_relative_filename))
  htmlbuilder = []
  # transformations: map from uuid to (line, startcolumn, textbeingreplaced, texttoreplaceitwith)
  # and then the form will just say which uuids to switch, and we can re parse those files
  # to make sure the relevant lines haven't been changed3
  transformations = {}
  print('swizzle_file', display_filename)
  # if preceded by href= then
  searches = [re.compile(r) for r in (
      r'(?<!'+urlregexps.urlchar+r')(?P<url>'+urlregexps.url+r')(?!'+urlregexps.urlchar+r')',
      r"'(?P<url>"+urlregexps.url_without_single_quotes+r")'",
      r'(?:\(|(?<!'+urlregexps.urlchar+r'))(?P<url>'+urlregexps.url_with_balanced_parentheses()+r')(?:\)|(?!'+urlregexps.urlchar+r'))',
      r'=(?P<url>'+urlregexps.url+r')(?!'+urlregexps.urlchar+r')',
      )]
  for lineno, line in enumerate(lines):
    idx = 0
    bestmatches = []
    while idx < len(line):
      # This algorithm is fairly inefficient but its precise semantics are
      # important (choosing the first match, more or less, out of several regexps).
      # TODO improve the speed.  Maybe the regexps can all be combined into one
      # regexp successfully, if it's okay not to discriminate based on which files
      # exist whoops.  And maybe run over the file, not individual lines,
      # but then how would I get line numbers.  Or maybe destfiles have to have
      # a '.' in them.  Or maybe I can turn 'existence' into a regexp as long
      # as I'm willing to miss things like "././foo"
      matches = tuple(filter(lambda m: m,
                             (s.match(line, idx) for s in searches)))
      existent_matches = tuple(filter(lambda m:
          url_file_exists(m.group('url'), filedirname, existence), matches))
      if len(existent_matches) == 0:
        idx += 1
      else:
        bestmatch = min(existent_matches, key=lambda m: (m.start('url'), -m.end('url')))
        idx = bestmatch.end()
        bestmatches.append(bestmatch)
    if len(bestmatches) == 0:
      continue
    linehtmlbuilder = []
    linehtmlbuilder.append('<p class="context"><span class="lineno">'
      +display_filename+':'+str(lineno+1)+'</span><span class="contextcontent">')
    idx = 0
    this_line_is_interesting = False
    def idxtill(nextloc):
      nonlocal idx
      if nextloc-idx > 80:
        linehtmlbuilder.append(html.escape(line[idx:idx+40]))
        linehtmlbuilder.append('<span class="ellipsis"> …… </span>')
        linehtmlbuilder.append(html.escape(line[nextloc-40:nextloc]))
      else:  
        linehtmlbuilder.append(html.escape(line[idx:nextloc]))
      idx = nextloc
    for match in bestmatches:
      (start, end) = match.span('url')
      # use [:] so we get '' rather than IndexError
      prevchar = line[start-1 : start]
      nextchar = line[end : end+1]
      # replace single quotes with double quotes
      singlequoted = (prevchar == "'" and nextchar == "'")
      equalled = (prevchar == '=')  #...and HTML ?
      if singlequoted:
        start -= 1
        end += 1
      url = match.group('url')
      orig_url_rr_match = re.match(r'^(?P<baseurl>.*)\?rr$', url)
      orig_has_rr = bool(orig_url_rr_match)
      if orig_url_rr_match:
        url = orig_url_rr_match.group('baseurl')
      plainurl = re.sub(queryandfragment_re, '', url)
      path = normpath(join(filedirname, plainurl))
      # Directory references have to be particularly likely to be
      # resource refs, because they visually appear more like more
      # things that are not resource refs.
      if existence[path] == False and not (
          prevchar in {'"',"'"} and nextchar in {'"',"'"}
          and line[start-5:start] != "href=" and line[start-6:start-1] != "href="):
        continue
      this_line_is_interesting = True
      idxtill(start)
      idx = end
      input_id = '{}:{}:{}'.format(display_filename, lineno, start)
      new_text = ''
      default_to_replace = (not orig_has_rr)
      linehtmlbuilder.append('<a href="javascript:;" class="modify {} {} {}">'.format(
          'default_on' if default_to_replace else 'default_off',
          'on' if default_to_replace else 'off',
          'orig_rr' if orig_has_rr else 'modified_rr'))
      linehtmlbuilder.append('<input type="checkbox" name="{}" {} class="modifyi" />'
          .format(html.escape(input_id), 'checked="checked"' if default_to_replace else ''))
      # TODO maybe use <label> and less JS
      #linehtmlbuilder.append('<input type="checkbox" name="{}" value="{}" class="modifyi" />'
      #    .format(html.escape(input_id), 'modified'))
      if singlequoted:
        linehtmlbuilder.append('''<span class="orig">'</span>''')
      if singlequoted or equalled:
        linehtmlbuilder.append('''<span class="modified">"</span>''')
        new_text += '"'
      linehtmlbuilder.append('''<span class="orig modified">''')
      linehtmlbuilder.append(html.escape(url))
      new_text += url
      linehtmlbuilder.append('''</span>''')
      linehtmlbuilder.append('''<span class="{}">?rr</span>'''.format(
          'orig' if orig_has_rr else 'modified'))
      if not orig_has_rr:
        new_text += '?rr'
      if singlequoted or equalled:
        linehtmlbuilder.append('''<span class="modified">"</span>''')
        new_text += '"'
      if singlequoted:
        linehtmlbuilder.append('''<span class="orig">'</span>''')
      linehtmlbuilder.append('</a>')
      transformations[input_id] = (cwd_relative_filename, lineno, start, line[start:end], new_text)
    idxtill(len(line.rstrip('\r\n')))
    linehtmlbuilder.append('</span></p>\n')
    if this_line_is_interesting:
      htmlbuilder.extend(linehtmlbuilder)
  return (''.join(htmlbuilder), transformations)

# encodings? i guess i can require only URLs to be utf-8 hmm
def looks_textual(file_bytes):
  return not any(c in file_bytes for c in
     b'\x00\x01\x02\x03\x04\x05\x06\x07\x08\x0E\x0F\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1A\x1B\x1C\x1D\x1E\x1F')

def swizzle(within_dir, post_path):
  """
  If abc and a=c and foo.html and index.html exist, offer:
  
  href=abc → href="abc?rr"
  href='abc' → href="abc?rr"
  href="abc" → href="abc?rr"
  href=a=c → href="./a=c?rr"
  href="a=c" → href="./a=c?rr"
  [](abc) → [](abc?rr)
  sourceMappingURL=abc → sourceMappingURL=abc?rr
  
  href=foo.html → href="foo"
  href=index.html → href="."
  """
  #editablelines = []
  htmlbuilder = []
#<script src="site/jquery-1.10.2.min.js"></script>
  htmlbuilder.append('''<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<title>Test</title>
<style>
/* CSS reset */
article,aside,figure,footer,header,hgroup,menu,nav,section{display:block;}
html,body,div,dl,dt,dd,ul,ol,li,h1,h2,h3,h4,h5,h6,pre,code,form,fieldset,legend,input,button,textarea,select,p,blockquote,th,td{margin:0;padding:0}
h1,h2,h3,h4,h5,h6{font-size:100%;font-weight:inherit;}
img{color:transparent;font-size:0;border:0;vertical-align:middle;-ms-interpolation-mode:bicubic;}

html,body {
  height: 100%;
  width: 100%;
  font-family: monospace;
  color: black;
  background-color: white;
}
a:link {
  color: #00ffff;
}
.contextcontent { color: gray; white-space: pre-wrap; }
a:link.modify {
  color: black;
}
.orig.modified { color: black; }
.orig:not(.modified), .modified:not(.orig) { font-weight: bold; }
a.modify.off .orig:not(.modified) { }
a.modify.on .orig:not(.modified) { color: red; text-decoration: line-through; display: inline; }
a.modify.off .modified:not(.orig) { display: none; }
a.modify.on .modified:not(.orig) { color: #00ff00; }
.lineno::after { color: black; content: ": "; }
</style>
<script>
'''+utils.read_file_text(join(dirname(__file__), "jquery-1.10.2.min.js"))+'''
</script>
<script>
$(function() {
  function select(a_element, newmodify) {
    if(newmodify) {
      $(a_element).addClass('on').removeClass('off');
    } else {
      $(a_element).removeClass('on').addClass('off');
    }
    $('input.modifyi', a_element).prop('checked', newmodify);
  }
  $('.modify').click(function() {
    select(this, !$(this).hasClass('on'));
  });
  $('#deselect_all').click(function() {
    $('a.modify').each(function() { select(this, false); });
  });
  $('#select_all').click(function() {
    $('a.modify').each(function() { select(this, true); });
  });
  $('#rrify_all').click(function() {
    $('a.modify.orig_rr').each(function() { select(this, false); });
    $('a.modify.modified_rr').each(function() { select(this, true); });
  });
  $('#unrrify_all').click(function() {
    $('a.modify.orig_rr').each(function() { select(this, true); });
    $('a.modify.modified_rr').each(function() { select(this, false); });
  });
  $('#defaults_all').click(function() {
    $('a.modify.default_off').each(function() { select(this, false); });
    $('a.modify.default_on').each(function() { select(this, true); });
  });
});
</script>
</head>
<body>
<form method="post" action="'''+html.escape(post_path)+'''">
<button>SUbMiT</button>
<button type="button" id="deselect_all">Deselect all</button>
<button type="button" id="select_all">Select all</button>
<button type="button" id="rrify_all">rr-ify all</button>
<button type="button" id="unrrify_all">un-rr-ify all</button>
<button type="button" id="defaults_all">reset to defaults</button>
''')
  # existence: dict from filepath relative to within_dir to
  # True/False (True: file; False: directory)
  existence = {}
  assert(exists(within_dir))
  only_this_file = None
  if not isdir(within_dir):
    only_this_file = basename(within_dir)
    within_dir = normpath(dirname(within_dir))
  existence.update({f: True for f in utils.relpath_files_under(within_dir)})
  existence.update({d: False for d in utils.relpath_dirs_under(within_dir)})
  transformations = {}
  for f in utils.relpath_files_under(within_dir) if only_this_file == None else [only_this_file]:
    #HACK for efficiency:
    if re.search(r'^words-int\.(js|json)$', basename(f)): continue
    
    filecontents = utils.read_file_binary(join(within_dir, f))
    if looks_textual(filecontents):
      fhtml, transf = swizzle_file(f, f, join(within_dir, f), filecontents, existence)
      assert(not any(k in transformations for k in transf))
      transformations.update(transf)
      htmlbuilder.append(fhtml)
  htmlbuilder.append('''</form></body></html>''')
  return (''.join(htmlbuilder), transformations)


def mutating_swizzle_file(f, linereplacements):
  lines = utils.read_file_text(f).splitlines(True)
  for lineno, line in enumerate(lines):
    for col, (was, willbe) in linereplacements.get(lineno, {}).items():
      if line[col:col+len(was)] != was:
        print("Error: file changed: {}".format(f))
        return
  builder = []
  for lineno, line in enumerate(lines):
    idx = 0
    for col, (was, willbe) in sorted(linereplacements.get(lineno, {}).items()):
      builder.append(line[idx:col])
      idx = col+len(was)
      builder.append(willbe)
    builder.append(line[idx:])
  utils.write_file_text(f, ''.join(builder))
    
def mutating_swizzle(possible_transformations, posted):
  mutate = []
  for name in posted:
    if name not in possible_transformations:
      print("Bad post data key: {}".format(name))
      return
    mutate.append(possible_transformations[name])
  # if we mutate from last to first then the line/column numbers won't shift around
  mutate_files = {}
  for f, line, col, was, willbe in mutate:
    mutate_files.setdefault(f, {}).setdefault(line, {})[col] = (was, willbe)
  for f, linereplacements in mutate_files.items():
    mutating_swizzle_file(f, linereplacements)

def main():
  try:
    site = sys.argv[1]
    os.stat(site)
  except (IndexError, FileNotFoundError, NotADirectoryError):
    print(usage)
    exit(1)
  get_path = '/'+utils.alnum_secret()
  post_path = '/'+utils.alnum_secret()
  htmlf, possible_transformations = swizzle(site, post_path)
  print(get_path)
  print(post_path)
  response_data = localwebfn.ask_for_POST(get_path, post_path, htmlf)
  posted = urllib.parse.parse_qs(response_data.decode('utf-8'))
  mutating_swizzle(possible_transformations, posted)
  print("done!")

if __name__ == '__main__':
  main()

