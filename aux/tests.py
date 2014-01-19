#!/usr/bin/python3

import re, traceback, sys, os, collections, urllib.parse, json
import asyncio

import private_configuration

# pip3 install --user http-parser
try:
    from http_parser.parser import HttpParser
except ImportError:
    from http_parser.pyparser import HttpParser


#attr kind: Int,  could be 0 to parseonly requests,
#  1 to parse only responses or 2 if we want to let
#  the parser detect the type.


# Wrapping http-parser package because its API fits poorly
# with our goals (esp. providing a recv_body() method but
# no const method to return the body).
class HttpResponse(object):
    def __init__(self, data):
        p = HttpParser(1)  # 0=request, 1=response, 2=autodetect
        p.execute(data, len(data))
        p.execute(b'', 0)  # end input
        self.status_code = p.get_status_code()
        self.headers = p.get_headers()
        self.body = p.recv_body()



loop = asyncio.get_event_loop()

class Client(asyncio.Protocol):
    def __init__(self, req):
        super(Client, self).__init__()
        self.req = req
        self.response = asyncio.Future()
        self.partial_response = bytearray()

    def connection_made(self, transport):
        #print('server established connection')
        transport.write(self.req.encode('utf-8'))
        #print('data sent: {}'.format(self.message))

    def data_received(self, data):
        #print('server sent data')
        self.partial_response.extend(data)
        #print('data received: {}'.format(data.decode()))

    def eof_received(self):
        #print('server sent eof')
        self.response.set_result(bytes(self.partial_response))

    def connection_lost(self, exc):
        pass
        #print('server closed the connection')


@asyncio.coroutine
def request(ip, port, request_data):
  _transport, client = yield from loop.create_connection(lambda: Client(request_data), ip, port)
  return (yield from client.response)


class statuses(object):
  unexpectedly_passed = 'unexpectedly passed'
  expectedly_broken = 'expectedly broken'
  failed = 'failed'
  passed = 'passed'
  statuses = (passed, failed, expectedly_broken, unexpectedly_passed)

  @classmethod
  def status(cls, passed, expect_broken = False):
    if passed and expect_broken: return cls.unexpectedly_passed
    if passed and not expect_broken: return cls.passed
    if not passed and expect_broken: return cls.expectedly_broken
    if not passed and not expect_broken: return cls.failed

def truncrepr(a):
  r = repr(a)
  return r if len(r) < 500 else r[:497]+'………'
    
class Test(object):
  def __init__(self, route, add_test_result):
    self.route = route
    self.add_test_result = add_test_result
  def __call__(self, *args): #desc = None, expect_broken = None, test_thunk):
    """
    test_object([desc], [expect_broken], test_thunk)
    Calls test_thunk() to run the test, expecting it to return a pair
      (passed, calleddesc) of a boolean
                  and a string describing the test and its arguments.
      
    Records the result by calling self.add_test_result(
      statuses.status(passed, expect_broken),
      a string describing the test based on desc etc).
    Returns a boolean that's True if the test passed, which can be useful
      if some tests are only worth running if this test passes.
    """
    desc = None
    expect_broken = False
    if len(args) == 1:
      test_thunk = args[0]
    if len(args) == 2:
      if isinstance(args[0], str): desc, test_thunk = args[0], args[1]
      else: expect_broken, test_thunk = args[0], args[1]
    if len(args) == 3:
      desc, expect_broken, test_thunk = args[0], args[1], args[2]
    if callable(expect_broken): expect_broken = expect_broken(self.route)
    elif isinstance(expect_broken, str): expect_broken = self.route == expect_broken
    elif isinstance(expect_broken, collections.Iterable): expect_broken = self.route in expect_broken
    try: passed, calleddesc = test_thunk()
    except (KeyError): passed, calleddesc = \
      False, '\n'+''.join(traceback.format_exception(*sys.exc_info())[2:])
    self.add_test_result(
      statuses.status(passed, expect_broken),
      "<{}> {}: {}".format(self.route, desc, calleddesc))
    return passed

  # These are suitable as __call__ test_thunk parameters as such:
  #   test(lambda: test.eq('x', 'y'))
  # TODO: remove the self parameter from these because it's unused?
  def re(self, re_, str_):
    return (bool(re.search(re_, str_)), 're.search({}, {})'.format(truncrepr(re_), truncrepr(str_)))
  def notre(self, re_, str_):
    return (not(re.search(re_, str_)), 'not re.search({}, {})'.format(truncrepr(re_), truncrepr(str_)))
  def bool(self, a): return (a, 'bool({})'.format(truncrepr(a)))
  def eq(self, a, b): return (a == b, '{} == {}'.format(truncrepr(a), truncrepr(b)))
  def ne(self, a, b): return (a != b, '{} != {}'.format(truncrepr(a), truncrepr(b)))
  def lt(self, a, b): return (a <  b, '{} < {}'.format(truncrepr(a), truncrepr(b)))
  def gt(self, a, b): return (a >  b, '{} > {}'.format(truncrepr(a), truncrepr(b)))
  def le(self, a, b): return (a <= b, '{} <= {}'.format(truncrepr(a), truncrepr(b)))
  def ge(self, a, b): return (a >= b, '{} >= {}'.format(truncrepr(a), truncrepr(b)))
  def in_(self, a, b): return (a in b, '{} in {}'.format(truncrepr(a), truncrepr(b)))
  def notin(self, a, b): return (a not in b, '{} not in {}'.format(truncrepr(a), truncrepr(b)))
  #def re(self, *args, **kwargs):
  #  return (bool(re.search(re_, str_)), 're.search({}, {})'.format(re_, str_)) #(re_, str_))


status_codes_to_test = {
	'/random-lwn': (301, '/random-lwn/'),
	'/random-lwn/': 200,
	'/Random-lwn/': 404, # test for case sensitivity and lack of auto spelling-correct based on Hamming distance or similar. The latter or both might be a good idea to do in some cases and make 301 redirects. But it's good to realize when it accidentally changes. I can change the test if I implement something else.
	'/random-lwn/go': 200,
	'/random-lwn/go/': (301, '/random-lwn/go'),
	'/random-lwn/go.html': 404,
	'/random-lwn/notgzipped,,go': 404,
	'/random-lwn/notgzipped,,go.html': 404,
	'/random-lwn/go.pl': 404,
	'/random-lwn/go.py': 404,
	'/random-lwn/go.asp': 404,
	'/random-lwn/go.shtml': 404,
	'/random-lwn/go.htm': 404,
	'/random-lwn/go.rb': 404,
	'/random-lwn/go.cgi': 404,
	'/random-lwn/go.php': 404,
	'/random-lwn/go.js': 404,
	'/random-lwn/index': 404,
	'/random-lwn/index.html': 404,
	'/random-lwn/index.html/': 404,
	'/index.html': 404,
	'/index': 404,
	'/': 200,
	'/.htaccess': 404,
	'/robots.txt': 200,
	'/thispagedoesntexist.png.exe': 404,
	'/t.gif': 200,
	'/robots.txt': 200,
	'/favicon.ico': 200,
	'/_resources': 404,
	'/_resources/': 404,
	'/four-color/': 200,
	# what about other things under /four-colour/ ?
	'/four-colour/': (301, '/four-color/'),
        '/four-colour': (301, '/four-color/'),
        '/four-color/Birkhoff-diamond/': 200,
        '/four-color/Birkhoff-diamond': (301, '/four-color/Birkhoff-diamond/'),
        '/four-color/Birkhoff diamond/': (301, '/four-color/Birkhoff-diamond/'),
        '/four-color/Birkhoff diamond': (301, '/four-color/Birkhoff-diamond/'),
	# what about making this work without cookies?
	'/starplay/': 200,
	'/lispy/': 200,
	'/haddock-presentation-2010/Haddock-presentation.png': 200,
	'/haddock-presentation-2010/Haddock-presentation-plain.svg': 200,
	'/haddock-presentation-2010/Haddock-presentation-inkscape.svg': 200,
	# Make sure various source directories that exist, have existed,
	# and/or may later exist, didn't get put onto the website by accident.
	'/nonresource-routes': 404,
	'/build/nonresource-routes': 404,
	'/+public-builds/build/nonresource-routes': 404,
	'/inotify-build-and-localupload': 404,
	'/inotify-build-and-localupload': 404,
	'/err/500.html': 404,
	'/err/500': 404,
	'/err/': 404,
	'/err': 404,
	'/aux': 404,
	'/aux/': 404,
	'/site': 404,
	'/site/': 404,
	'/compile': 404,
	'/compile/': 404,
	'/compile/go': 404,
	'/compile/tests.js': 404,
	'/compile/compile': 404,
	'/compile/compile.js': 404,
	'/srv': 404,
	'/srv/': 404,
	'/srv/openresty': 404,
	'/srv/openresty/': 404,
	'/srv/openresty/prefix': 404,
	'/srv/openresty/prefix/': 404,
	'/srv/openresty/conf': 404,
	'/srv/openresty/conf/': 404,
	'/conf': 404,
	'/conf/': 404,
	'/conf/init.lua': 404,
	'/conf/nginx.conf': 404,
	'/conf/pagecontent': 404,
	'/conf/pagecontent/': 404,
	'/prefix': 404,
	'/prefix/': 404,
	'/.gitignore': 404,
	'/err/.gitignore': 404,
	'/.git': 404,
	'/.git/': 404,
	'/.git/config': 404,
	'/i': 404,
	'/i/': 404,
}
def get_status_code_to_test(route):
  try: return status_codes_to_test[route][0]
  except TypeError: return status_codes_to_test[route]
  except KeyError: return None
def get_redirect_target_to_test(route):
  try: return status_codes_to_test[route][1]
  except (KeyError, TypeError): return None

#TODO autogen these (and 'test' that certain paths are in them,
#incl robots.txt and favicon.ico and / and /various
#TODO move some pages to /2013/
#TODO check for nonbroken redirects and external links? separately?
# and test that some are subsets of others)
#also what about multi domain routes


the_domain = 'http://www.idupree.com'
# is this sensible?
def dedomain(url):
  return re.sub(r'^'+re.escape(the_domain), '', url)

os.chdir(os.path.dirname(os.path.join('.', __file__)))
os.chdir('..')
# The transparent gif will never change meaning, so it's fine
# as a well-known nigh-forever-cacheable name.
with open('../+public-builds/build/nocdn-resource-routes', 'r') as f:
  resource_routes = set(map(dedomain, f.read().split('\n'))) | {'/t.gif'}
with open('../+public-builds/build/nonresource-routes', 'r') as f:
  nonresource_routes = set(map(dedomain, f.read().split('\n')))

existent_routes = resource_routes | nonresource_routes
tested_routes = existent_routes | set(status_codes_to_test)



def is_active_content_type(t):
  return t and re.search(r'text/html|application/xhtml+xml|image/svg+xml', t)

@asyncio.coroutine
def test_http_response(ip, port, route, response):
    resp = HttpResponse(response)
    results = []
    test = Test(route, lambda p,d: results.append((p,d)))

    test('has Date', lambda:test.in_('Date', resp.headers))
    if 'Content-Length' in resp.headers:
      test('has correct Content-Length', lambda:test.eq(int(resp.headers['Content-Length']), len(resp.body)))
    test('no Server', lambda:test.notin('Server', resp.headers))
    test('no Last-Modified', lambda:test.notin('Last-Modified', resp.headers))

    if route in existent_routes:
      test("status 200 or such", lambda:test.in_(resp.status_code, {200, 301, 302, 303, 307, 410}))
      if resp.status_code == 200:
        test('has ETag', lambda:test.in_('ETag', resp.headers))
        test('has Content-Length', lambda:test.in_('Content-Length', resp.headers))
        if route in nonresource_routes:
          # TODO allow it if there are other Link: headers also:
          # search Link: headers for it.
          test("HTTP Link rel=canonical", lambda:test.eq(resp.headers['Link'], '<http://www.idupree.com{}>; rel="canonical"'.format(route)))
    else:
      # TODO allow it if there are other Link: headers also:
      # search Link: headers for it.
      test("Has no HTTP Link rel=canonical", lambda:test.notin('Link', resp.headers))

    if route in status_codes_to_test:
      test("status matches expectation", lambda:test.eq(resp.status_code,
        get_status_code_to_test(route)))

    if get_redirect_target_to_test(route):
      test("redirects to the correct place", lambda:test.eq(resp.headers['Location'],
        the_domain+get_redirect_target_to_test(route)))

    if route == '/favicon.ico':
      # An out-of-date favicon isn't very serious
      test('favicon cacheable for medium duration', lambda:test.re(r'^max-age=[0-9]{6}$', resp.headers["Cache-Control"]))
      # IE < 11 only supports ico favicons
      test('favicon is ico', lambda:test.eq(resp.headers['Content-Type'], 'image/x-icon'))

    elif route not in resource_routes:
      test('not lengthily cacheable', lambda:test.notre(r'max-age=[0-9]{5,}', resp.headers.get("Cache-Control", '')))

    test('noarchive', lambda:test.re(r'noarchive', resp.headers['X-Robots-Tag']))
    if re.search(r'^/_resources/style\.[^/]*\.css$', route):
      # test that a public resource file is not mistakenly specified noindex
      test('indexable', lambda:test.notre(r'noindex', resp.headers['X-Robots-Tag']))
    if the_domain+route in private_configuration.doindexfrom:
      # At minimum these pages should lack noindex
      test('indexable', lambda:test.notre(r'noindex', resp.headers['X-Robots-Tag']))
    if the_domain+route in private_configuration.butdontindexfrom:
      # At minimum these pages should have noindex
      test('noindex', lambda:test.re(r'noindex', resp.headers['X-Robots-Tag']))

    #TODO list types that are inactive instead, for better caution
    if is_active_content_type(resp.headers.get('Content-Type')):
      test('X-Frame-Options: SAMEORIGIN', lambda:test.eq(resp.headers['X-Frame-Options'], 'SAMEORIGIN'))
    
    if re.search(r'text/html', resp.headers.get('Content-Type', '')):
      test('content-type: text/html; charset=utf-8', lambda:test.eq(resp.headers['Content-Type'], 'text/html; charset=utf-8'))
      test('contains charset utf-8', lambda:test.re(br'''charset=['"]?utf-8''', resp.body))
      test('does not refer to an SCSS mime type', lambda:test.notre(br'text/scss', resp.body))
      test('does not contain @mixin or @include', lambda:test.notre(br'@mixin|@include', resp.body))
      if route in existent_routes:
        test('has rel=canonical of idupree.com', lambda:test.re(br'''<link rel="canonical" href="http://www\.idupree\.com'''+re.escape(route).encode('utf-8')+br'"\s*/?>', resp.body))
      else:
        test('has no <link rel="canonical">', lambda:test.notre(br'''<link rel="canonical"''', resp.body))

      # Unfortunately, the validator refuses to validate the HTML contents
      # of pages whose HTTP status is 404.
      if route in existent_routes:
        # The validator is slightly unhappy about redundant ":80" in URLs
        tested_page_path = ('http://{}:{}{}'.format(ip, port, route) if port != 80 else
                            'http://{}{}'.format(ip, route))
        validate_req = ('''GET /?parser=html5&out=json&doc={} HTTP/1.0\r\n\r\n'''
            .format(urllib.parse.quote(tested_page_path, '')))
        #TODO flexible IP/ports for running the validator
        validation_response = HttpResponse((yield from request('127.0.0.1', 8888, validate_req)))
        test('HTML5 validator working',
             lambda:test.eq(200, validation_response.status_code))
        try:
          validation_response_parsed = json.loads(validation_response.body.decode('utf-8'))
          messages = validation_response_parsed["messages"]
          # Assume messages are bad unless we've seen them and decided
          # they're okay.  The validator mostly only emits messages for
          # actual problems.
          def message_is_alright(message):
            # This validation error is deliberate in an attempt to reduce
            # spambot email harvesting.  The nonconformance appears not to
            # cause issues in common browsers.
            return None != re.search(
              r'^Bad value “maILtO:.*” for attribute “href” on element “a”: Control character in path component\.$',
              message["message"],
              re.DOTALL)
          def message_indicates_a_bad_thing(message):
            return not message_is_alright(message)
          bad_messages = tuple(filter(message_indicates_a_bad_thing, messages))
          test('validates as HTML5 (validator.nu checker)',
               lambda:test.eq((), bad_messages))
        except (ValueError, KeyError):
          test('HTML5 validator working as expected', lambda:test.eq(False, validation_response.body))
    
    if re.search(r'text/css', resp.headers.get('Content-Type', '')):
      test('content-type: text/css; charset=utf-8', lambda:test.eq(resp.headers['Content-Type'], 'text/css; charset=utf-8'))
      test('begins with @charset "UTF-8";', lambda:test.re(br'^@charset "UTF-8";', resp.body))
      test('does not contain @mixin or @include', lambda:test.notre(br'@mixin|@include', resp.body))

    if re.search(r'javascript', resp.headers.get('Content-Type', '')):
      test('content-type: application/javascript; charset=utf-8', lambda:test.eq(resp.headers['Content-Type'], 'application/javascript; charset=utf-8'))
      

    if route in resource_routes:
      test('far future Cache-Control', lambda:test.re(r'^max-age=[0-9]{7,8}$', resp.headers["Cache-Control"]))
      test('obscure name (or /t.gif)', lambda:test.re(r'^/t\.gif$|\.[-0-9a-zA-Z_]{15}(\.|$)', route))

    if route == '/':
      #TODO create my own local spampoison pages
      test('front page contains spampoison', lambda:test.re(br'spampoison', resp.body))

    if route == '/robots.txt':
      test('reasonable robots.txt Cache-Control', lambda:test.notin('Expires', resp.headers))
      test('reasonable robots.txt Cache-Control', lambda:test.eq(resp.headers['Cache-Control'], 'max-age=15, must-revalidate'))

    if route == '/favicon.ico':
      #or TODO redirect? I guess I don't gain much with that, since
      # revalidation will be needed anyway and favicons aren't big
      # enough that it's worth cdn'ing them on top of the http 30x probably
      test('site has a favicon', lambda:test.eq(resp.status_code, 200))

    # TODO check this better:
    test('vary accept-encoding', lambda:test.bool('Content-Encoding' not in resp.headers or re.search(r'Accept-Encoding', resp.headers['Vary'])))
    if resp.headers.get('Content-Type') in {'text/html', 'text/css', 'application/javascript'}:
      test('vary accept-encoding', lambda:test.re(r'Accept-Encoding', resp.headers['Vary']))
    if resp.headers.get('Content-Type') in {'image/png', 'image/jpeg'}:
      test('No Vary', lambda:test.notin('Vary', resp.headers))

    

    return results

@asyncio.coroutine
def do_tests(ip, port):
  @asyncio.coroutine
  def get(path):
    """
    non gzipped version
    """
    return (yield from request(ip, port,
      'GET {} HTTP/1.1\r\nConnection: close\r\nHost: www.idupree.com\r\n\r\n'.format(path)))

  @asyncio.coroutine
  def test_route(route):
    return (yield from test_http_response(ip, port, route, (yield from get(route))))

  test_results = map(asyncio.Task, map(test_route, tested_routes))

  results, [] = (yield from asyncio.wait(test_results))
  results = map(lambda x: x.result(), results)
  counts = {s: 0 for s in statuses.statuses}
  for result in sorted(results):
    for status, desc in result:
     counts[status] += 1
     if status in (statuses.failed, statuses.unexpectedly_passed):
       print('    ' + status + ': ' + desc + '\n')
  print()
  for k, v in counts.items():
    if v > 0:
      print(k+': '+str(v))


c = do_tests('127.0.0.1', 8080)
loop.run_until_complete(c)

