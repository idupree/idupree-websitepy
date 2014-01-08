#!/usr/bin/python3
# -*- coding: utf-8 -*-
#from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
from http.server import BaseHTTPRequestHandler, HTTPServer
import re, shutil, html, webbrowser, urllib
from os.path import exists, join, isfile, normpath, dirname, basename
import create_secrets
import urlregexps
import utils


def ask_for_POST(get_path, post_path, html_to_serve_on_get_path, port_number = 9999):
  """
  Runs a local web server and browser UI; returns when the browser
  posts to post_path and returns the contents of the POST body.
  """
  already_gotten = False
  already_posted = False
  response_data = None
  class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
      if self.path != get_path:
        self.send_error(404)
      else:
        nonlocal already_gotten
        if already_gotten:
          self.send_error(403, "WARNING SIRENS: SOMEONE GOT THERE BEFORE YOU")
        else:
          already_gotten = True
          self.send_response(200)
          self.send_header('Content-Type', 'text/html; charset=utf-8')
          self.end_headers()
          self.wfile.write(html_to_serve_on_get_path.encode('utf-8'))

    def do_POST(self):
      if self.path != post_path:
        self.send_error(404)
      else:
        # Hmm this seems unreliable but I don't know if there's
        # a packaged solution for http.server
        length = int(self.headers['Content-Length'])
        nonlocal response_data
        response_data = self.rfile.read(length)
        nonlocal already_posted
        already_posted = True
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'Successfully posted.')
  server = HTTPServer(('', port_number), Handler)
  #TODO race condition? or does the HTTPServer constructor open the port?
  webbrowser.open('http://localhost:{}{}'.format(port_number, get_path))
  while not already_posted: server.handle_request()
  return response_data



queryandfragment_re = re.compile(r'[?#].*')
nonrelativeurl_re = re.compile(urlregexps.urlwithdomain+'|'+urlregexps.domainrelativeurl)
def url_file_exists(url, filedirname, existence):
  # TODO relpath and url rel correctly, crib from existing work in fake spider in build.py
  # TODO fewer syscalls; memoize?
  # TODO directory references often shouldn't be listed; exists/isdir/islink...
  if re.search(nonrelativeurl_re, url):
    ret = False
  else:
    path = normpath(join(filedirname, re.sub(queryandfragment_re, '', url)))
    ret = (path in existence and existence[path] == True)
    #ret = isfile(re.sub(r'[?#].*', '', normpath(join(dirname(filename), url))))
  #print('testing existence of:' + url, ':', ret)
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
    #print(lineno)
    idx = 0
    #print('Analyzing:', line)
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
        #print('chose:', str(bestmatch.start())+':'+bestmatch.group(), 'as', bestmatch.re.pattern)
        idx = bestmatch.end()
        bestmatches.append(bestmatch)
    if len(bestmatches) == 0:
      continue
    linehtmlbuilder = []
    linehtmlbuilder.append('<p class="context"><span class="lineno">'
      +display_filename+':'+str(lineno+1)+'</span><span class="contextcontent">')
    #print('Done analyzing:', line)
    #for match in re.finditer(urlregexps.urlchar+'+', line):
    #  linehtmlbuilder.append(html.escape(line[idx:match.start()]))
    #  idx = match.end()
    idx = 0
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
      idxtill(start)
      idx = end
      input_id = '{}:{}:{}'.format(display_filename, lineno, start)
      new_text = ''
      default_to_replace = (not orig_has_rr)
      linehtmlbuilder.append('<a href="javascript:;" class="modify {}">'.format(
          'on' if default_to_replace else 'off'))
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
      
      #linehtmlbuilder.append(html.escape(line[idx:match.start('url')]))
      #idx = match.end('url')
      #adding = lineno % 2 == 0  #lol test hack
      #linehtmlbuilder.append(
      #  '<a href="javascript:;" class="modify"><span class="orig">'
      #  #+html.escape(match.group())
      #  +html.escape(match.group('url'))
      #  +('</span>' if adding else '')
      #  +'<span class="toggle on">?rr</span>'+('' if adding else '</span>')
      #  +'</a>')
    idxtill(len(line.rstrip('\r\n')))
    #linehtmlbuilder.append(html.escape(line[idx:].rstrip('\r\n')))
    linehtmlbuilder.append('</span></p>\n')
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
/*
.orig { color: black; }
.orig .toggle.on { color: blue; }
.orig .toggle.off { color: red; text-decoration: line-through; display: inline; }
.toggle.on { color: green; }
.toggle.off { display: none; }
.toggle.off { xcolor: yellow; }*/
/*.modify { cursor: pointer; }
.modify:hover, .modify:active, .modify:focus { text-decoration: underline; }*/
.lineno::after { color: black; content: ": "; }
</style>
<script>
'''+utils.read_file_text("site/jquery-1.10.2.min.js")+'''
</script>
<script>
$(function() {
  $('.modify').click(function() {
    var newmodify = !$(this).hasClass('on');
    //if(newmodify) {
    //  $(this).addClass('on').removeClass('off');
    $(this).toggleClass('on').toggleClass('off');
    $('input.modifyi', this).prop('checked', newmodify);
    //$('input.modifyi', this)
    //$(this).toggleClass('on').toggleClass('off');
    //$('.toggle', this).toggleClass('on').toggleClass('off');
  });
// .mousedown(function(e) { e.preventDefault() }); //stops doubleclick.. and click+drag.. selection
// http://stackoverflow.com/questions/880512/prevent-text-selection-after-double-click
});
</script>
</head>
<body>
<form method="post" action="'''+html.escape(post_path)+'''">
<button>SUbMiT</button>
''')
  # existence: dict from filepath relative to within_dir to
  # True/False (True: file; False: directory)
  existence = {}
  existence.update({f: True for f in utils.relpath_files_under(within_dir)})
  existence.update({d: False for d in utils.relpath_dirs_under(within_dir)})
  transformations = {}
  for f in utils.relpath_files_under(within_dir):
    #HACK for efficiency:
    if re.search(r'^words-int\.(js|json)$', basename(f)): continue
    
    filecontents = utils.read_file_binary(join(within_dir, f))
    if looks_textual(filecontents):
      fhtml, transf = swizzle_file(f, f, join(within_dir, f), filecontents, existence)
      assert(not any(k in transformations for k in transf))
      transformations.update(transf)
      htmlbuilder.append(fhtml)
      #htmlbuilder.append(swizzle_file(f, join(within_dir, f), filecontents, existence))
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
    
# buttons 'select all' / 'deselect all' / 'unrr all'
    
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
  #made testsite so mutation doesnt bug me all up
  site = 'testsite/starplay/v2'
  get_path = '/'+create_secrets.alnum_secret()
  post_path = '/'+create_secrets.alnum_secret()
  htmlf, possible_transformations = swizzle(site, post_path)
  print(get_path)
  print(post_path)
  response_data = ask_for_POST(get_path, post_path, htmlf)
  posted = urllib.parse.parse_qs(response_data.decode('utf-8'))
  mutating_swizzle(possible_transformations, posted)
  print("done!")

if __name__ == '__main__':
  main()




    # do several searches
    # urlchar+              (double-quoted anywhere)
    # 'nonquoteurlchar+'    (css, js)
    # [(nonurlchar]balancedparenurl[)nonurlchar]    (markdown, css url())
    # =urlchar+    (sourceMappingURL=, href=)
    # 
    # allow match where url is a file or such. (html unescape? +/- ?rr, .html, index.html?)
    # prefer the match that start()s earliest in the line.
    # then repeat, from end().
    #
    # [urlchar+    (mediawiki)
    # try every match even if they overlap, somehow? for mediawiki.
    # no wait thats fine?
    #
    # things this will miss:
    # css/js referencing 'matan\'s-hair.png' rather than "matan's-hair.png", or
    #   gratuitously using \ in url strings.
    # in html, &amp; and &variousstuff; in urls preceding the ?# parts; although
    # currently my code is broken with those anyway, and all of them except for
    # non-percent-encoded-& can be represented in Unicode directly.
    # i'll need & in urls though...4color stuff uses it.
    # "/&amp;" and "/&" are both valid urls, alas! and html can contain <script>
    # that lacks entity-expansion.  but..rr stuff neednt have '&' files i think,
    # it's just the spider that has to deal with it
    #
    # () not replaced, '' replaced with "" probably, 
    # So the = issue is that ?rr doesnt show the begin the way {{}} does, hmm...
    # well i could require in some cases for the beginning to be /|./|../
    # (?!(?<!urlchar)[alnum]+=[./])
    # or better lets see, any = in the url must be preceded by a /, and the url
    # can be preceded by =.  also the url can probably robustly be in '' but i think i dont need that
    # oh this in markdown: [Google](http://google.com/ "Google")
    # ![alttext](./a(b)c.png?rr)
    # 
    # (?<!urlchar)[urlchar - =()[]']*(?:/[urlchar]*)?\?rr(?![urlchar - )\]'])
    # or remove ' , [ ?
    # should : also allow other chars after it? allowing "mailto:%22e=vil%22@evil.com"
    # which is actually also RFC822-legal as "mailto:e=vil@evil.com"
    # not that ?rr can do anything with mailto nor absolute refs... hmm...
    # and banning xpath:attr=./foo?rr (although in xml the quotes would be needed)
    # mailto:?e=vil@evil.com?rr
    # mailto:?rr=e=vil@evil.com?rr
    # nevermind
    # hmm markdown [wahh/](x.png?rr) or [wahh/](./x.png?rr) won't work hmm.
    # it'll find wahh/](x.png?rr, or it won't because preceding [ but better bug:
    # [ah hah/](x.png?rr) ---> hah/](x.png?rr
    # I could require any with special chars to start with /|./|../, in which case
    # [ah /hah](x.png?rr) ---> /hah](x.png?rr
    # At least there'll be error msgs that that path doesn't exist...
    # [ah (./hah/](x.png?rr) ---> ./hah/](x.png?rr
    # [ah (./hah/](x.png?rr titletext) ---> ./hah/](x.png?rr
    # [ah ./hah/](x.png?rr titletext) ---> ./hah/](x.png?rr
    # also the transformed version might (in HTML) *need* double-quotes
    # Maybe I should special case sourceMappingURL?
    # i think the "/ before =" rule might be the least trouble
    # oh because of 


#server.serve_forever()
#except KeyboardInterrupt:
#  print('^C received, shutting down the web server')
#  server.socket.close()

#      self.send_response(404)
#      self.send_header('Content-Type', 'text/plain')
#      self.end_headers()
#      self.wfile.write(b"404 Not Found")
#      return
      #return #
      #self.server.shutdown()
      #raise Done()

#class Done(BaseException):
#  pass
#      self.send_response(200)
#      self.send_header('Content-Type', 'text/plain')
#      self.end_headers()
#      self.wfile.write(b'Success.')
#      self.wfile.write(b'''<!DOCTYPE html><title>Success!</title><script>window.open('','_parent',''); close()</script><p>Success.</p>''')
    #line_rest = line
'''
      matches = tuple(filter(lambda m: m,
                             (re.search(s, line_rest) for s in searches)))
      print('unfiltered:', *[str(m.start())+':'+m.group()+' ' for m in matches])
      if len(matches) == 0:
        break
      existent_matches = tuple(filter(lambda m: url_file_exists(m.group('url')), matches))
      if len(existent_matches) == 0:
        line_rest = line_rest[min(m.end() for m in matches):]
        continue
      print('filtered:', *[str(m.start())+':'+m.group()+' ' for m in existent_matches])
      bestmatch = min(existent_matches, key=lambda m:m.start())
      print('chose:', str(bestmatch.start())+':'+bestmatch.group())
      line_rest = line_rest[bestmatch.end():]
      #print bestmatch.span()
      '''
