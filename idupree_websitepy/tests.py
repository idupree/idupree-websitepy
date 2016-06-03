
import re, traceback, sys, os, collections, urllib.parse, json, collections
import asyncio
from email import message_from_bytes

# we expect a Config object such as idupree_websitepy.build.Config
#from .build import Config


# HTTP headers are RFC2822 headers and python doesn't come with
# a more straightforward interface for HTTP header parsing
# (aside from one hidden in the implementations of http.client/http.server).
# See https://stackoverflow.com/questions/4685217/parse-raw-http-headers
class HttpResponse(object):
    def __init__(self, data):
        status_line, rest = data.split(b'\r\n', 1)
        self.http_version, status_code, self.status_reason_phrase = \
          re.search(br'^(HTTP/1\.[01]) ([0-9]*) (.*)$', status_line).groups()
        self.status_code = int(status_code)
        message = message_from_bytes(rest)
        self.headers = collections.OrderedDict(message.items())
        self.body = message.get_payload().encode('utf-8')



def loop():
    return asyncio.get_event_loop()

class Client(asyncio.Protocol):
    def __init__(self, req):
        super(Client, self).__init__()
        if isinstance(req, bytes):
          self.req = req
        else:
          self.req = req.encode('utf-8')
        self.response = asyncio.Future()
        self.partial_response = bytearray()

    def connection_made(self, transport):
        #print('server established connection')
        transport.write(self.req)
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


num_total_requests = 0
num_outstanding_requests = 0
max_outstanding_requests = 8

@asyncio.coroutine
def request(host, port, request_data):
  global num_outstanding_requests
  global num_total_requests
  num_total_requests += 1
  request_num = num_total_requests
  sys.stderr.write("Request {} requested; outstanding requests: {}\n".format(request_num, num_outstanding_requests))
  while num_outstanding_requests >= max_outstanding_requests:
    yield from asyncio.sleep(0.05)
  num_outstanding_requests += 1
  sys.stderr.write("Request {} began    ; outstanding requests: {}\n".format(request_num, num_outstanding_requests))
  transport, client = yield from loop().create_connection(lambda: Client(request_data), host, port)
  response = yield from client.response
  transport.close()
  num_outstanding_requests -= 1
  sys.stderr.write("Request {} finished ; outstanding requests: {}\n".format(request_num, num_outstanding_requests))
  # (TODO record time taken waiting for request, and what the request was, perhaps, for speed debugging)
  return response

@asyncio.coroutine
def http_request(host, port, path, method = 'GET', host_header = None):
  """
  non gzipped version
  host_header defaults to host
  """
  if host_header == None:
    host_header = host
  return (yield from request(host, port,
    '{} {} HTTP/1.1\r\nConnection: close\r\nHost: {}\r\n\r\n'.format(method, path, host_header)))

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

def get_status_code_to_test(config, route):
  try: return config.test_status_codes[route][0]
  except TypeError: return config.test_status_codes[route]
  except KeyError: return None
def get_redirect_target_to_test(config, route):
  try:
    r = config.test_status_codes[route][1]
  except (KeyError, TypeError):
    return None
  if r[:1] == '/':
    return test_scheme_domain_port_string_for_redirects(config) + r
  else:
    return r

#TODO autogen these (and 'test' that certain paths are in them,
#incl robots.txt and favicon.ico and / and /various
#TODO move some pages to /2013/
#TODO check for nonbroken redirects and external links? separately?
# and test that some are subsets of others)
#also what about multi domain routes


# is this sensible?
def dedomain(url):
  return re.sub(r'^(https?|file)://[^/]*', '', url)


def is_active_content_type(t):
  return t and re.search(r'text/html|application/xhtml+xml|image/svg+xml', t)

def test_scheme_domain_port_string_for_redirects(config):
  return (
    'http://' +
    config.test_host_header +   #or canonical? or?
    (':'+str(config.test_port) if config.test_port != 80 else ''))

@asyncio.coroutine
def test_route(config, route):
    method = 'GET' if config.test_all_content_lengths else 'HEAD'
    response = yield from http_request(config.test_host, config.test_port, route, method, config.test_host_header)
    resp = HttpResponse(response)
    headers = resp.headers
    status_code = resp.status_code
    content_type = headers.get('Content-Type', '')

    if method == 'GET':
      body = resp.body
    if method == 'HEAD' and re.search(r'text/html|text/css', content_type):
      method = 'GET'
      response = yield from http_request(config.test_host, config.test_port, route, method, config.test_host_header)
      resp = HttpResponse(response)
      body = resp.body

    results = []
    test = Test(route, lambda p,d: results.append((p,d)))

    test('has Date', lambda:test.in_('Date', headers))

    if 'Content-Length' in headers and method == 'GET':
      test('has correct Content-Length', lambda:test.eq(int(headers['Content-Length']), len(body)))

    test('no Server', lambda:test.notin('Server', headers))
    test('no Last-Modified', lambda:test.notin('Last-Modified', headers))

    if route in config.tests_existent_routes:
      test("status 200 or such", lambda:test.in_(status_code, {200, 301, 302, 303, 307, 410}))
      if status_code == 200:
        test('has ETag', lambda:test.in_('ETag', headers))
        test('has Content-Length', lambda:test.in_('Content-Length', headers))
        if config.test_canonical_origin != None and route in config.tests_nonresource_routes:
          # TODO allow it if there are other Link: headers also:
          # search Link: headers for it.
          test("HTTP Link rel=canonical", lambda:test.eq(headers['Link'],
            '<{}{}>; rel="canonical"'.format(config.test_canonical_origin, route)))
    else:
      # TODO allow it if there are other Link: headers also:
      # search Link: headers for it.
      test("Has no HTTP Link rel=canonical", lambda:test.notin('Link', headers))

    if route in config.test_status_codes:
      test("status matches expectation", lambda:test.eq(status_code,
        get_status_code_to_test(config, route)))

    if get_redirect_target_to_test(config, route):
      test("redirects to the correct place", lambda:test.eq(headers['Location'],
        get_redirect_target_to_test(config, route)))

    if route == '/favicon.ico':
      # An out-of-date favicon isn't very serious
      test('favicon cacheable for medium duration', lambda:test.re(r'^max-age=[0-9]{6}$', headers["Cache-Control"]))
      # IE < 11 only supports ico favicons
      test('favicon is ico', lambda:test.eq(content_type, 'image/x-icon'))

    elif route not in config.tests_resource_routes:
      test('not lengthily cacheable', lambda:test.notre(r'max-age=[0-9]{5,}', headers.get("Cache-Control", '')))

    test('noarchive', lambda:test.re(r'noarchive', headers['X-Robots-Tag']))
    if re.search(r'^/_resources/style\.[^/]*\.css$|^/$|^/README$|^/pgp$', route):
      # test that a public resource file is not mistakenly specified noindex
      test('indexable', lambda:test.notre(r'noindex', headers['X-Robots-Tag']))
    if config.canonical_scheme_and_domain + route in config.doindexfrom:
      # At minimum these pages should lack noindex
      test('indexable', lambda:test.notre(r'noindex', headers['X-Robots-Tag']))
    if config.canonical_scheme_and_domain + route in config.butdontindexfrom:
      # At minimum these pages should have noindex
      test('noindex', lambda:test.re(r'noindex', headers['X-Robots-Tag']))

    #TODO list types that are inactive instead, for better caution
    if is_active_content_type(content_type):
      test('X-Frame-Options: SAMEORIGIN', lambda:test.eq(headers['X-Frame-Options'], 'SAMEORIGIN'))
    
    if re.search(r'text/html', content_type):
      test('content-type: text/html; charset=utf-8', lambda:test.eq(content_type, 'text/html; charset=utf-8'))
      test('contains charset utf-8', lambda:test.re(br'''charset=['"]?utf-8''', body))
      test('does not refer to an SCSS mime type', lambda:test.notre(br'text/scss', body))
      test('does not contain @mixin or @include', lambda:test.notre(br'@mixin|@include', body))
      if route in config.tests_existent_routes:
        if config.test_canonical_origin != None:
          test('has rel=canonical of '+config.test_canonical_origin,
            lambda:test.re(br'''<link rel="canonical" href="''' +
              re.escape(config.test_canonical_origin + route).encode('utf-8') +
              br'"\s*/?>', body))
      else:
        test('has no <link rel="canonical">', lambda:test.notre(br'''<link rel="canonical"''', body))

      # Unfortunately, the validator refuses to validate the HTML contents
      # of pages whose HTTP status is 404.
      if route in config.tests_existent_routes:
        # POST body now is the preferred way to use the validator,
        # it lets you specify Content-Type, and the remote-request
        # mechanism was having random time outs when testing hundreds
        # of connections at once to my server remotely (with no way
        # to configure the timeout interval that I saw).
        #
        # https://github.com/validator/validator/wiki/Service%3A-Input%3A-POST-body
        #
        # So this code no longer uses the GET method
        # https://github.com/validator/validator/wiki/Service%3A-Input%3A-GET
        # as follows.
        #
        # The validator is slightly unhappy about redundant ":80" in URLs
        #tested_page_path = ('http://{}:{}{}'.format(ip, port, route) if port != 80 else
        #                    'http://{}{}'.format(ip, route))
        #validate_req = ('''GET /?parser=html5&out=json&doc={} HTTP/1.0\r\n\r\n'''
        #    .format(urllib.parse.quote(tested_page_path, '')))

        # Make sure not to get number of codepoints by accident
        # when taking len(body) - we want number of octets
        assert(isinstance(body, bytes))
        validate_req = (
          b'POST /?parser=html5&out=json HTTP/1.0\r\n'+
          b'Content-Type: '+content_type.encode('utf-8')+b'\r\n'+
          b'Content-Length: '+str(len(body)).encode('utf-8')+b'\r\n'+
          b'\r\n'+
          body
          )
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
          is_twine = False
          def message_is_alright(message):
            # Unfortunately Twine-generated HTML does not validate at all.
            nonlocal is_twine
            if is_twine:
              return True
            if None != re.search(r'^Element “tw-story”', message["message"]):
              is_twine = True
              return True
            # This validation error is deliberate in an attempt to reduce
            # spambot email harvesting.  The nonconformance appears not to
            # cause issues in common browsers.
            if re.search(
                r'^Bad value “maILtO:.*” for attribute “href” on element “a”: Illegal character in scheme data: not a URL code point\.$',
                message["message"],
                re.DOTALL):
              return True
            # Pandoc doesn't seem to have a way to put a <h2>Footnotes</h2>
            # at the top of its footnotes, unless I missed something :-(
            if (message['type'] == 'info' and
                re.search(r'^Section lacks heading\.', message['message']) and
                re.search(r'<section class="footnotes">', message['extract'])):
              return True
            return False

          def message_indicates_a_bad_thing(message):
            return not message_is_alright(message)
          bad_messages = tuple(filter(message_indicates_a_bad_thing, messages))
          test('validates as HTML5 (validator.nu checker)',
               lambda:test.eq((), bad_messages))
        except (ValueError, KeyError):
          test('HTML5 validator working as expected', lambda:test.eq(False, validation_response.body))
    
    if re.search(r'text/css', content_type):
      test('content-type: text/css; charset=utf-8', lambda:test.eq(content_type, 'text/css; charset=utf-8'))
      test('begins with @charset "UTF-8";', lambda:test.re(br'^@charset "UTF-8";', body))
      test('does not contain @mixin or @include', lambda:test.notre(br'@mixin|@include', body))

    if re.search(r'javascript', content_type):
      test('content-type: application/javascript; charset=utf-8', lambda:test.eq(content_type, 'application/javascript; charset=utf-8'))
      

    if route in config.tests_resource_routes:
      test('far future Cache-Control', lambda:test.re(r'^max-age=[0-9]{7,8}$', headers["Cache-Control"]))
      test('obscure name (or /t.gif)', lambda:test.re(r'^/t\.gif$|\.[-0-9a-zA-Z_]{15}([./]|$)', route))

    if route == '/':
      #TODO create my own local spampoison pages
      test('front page contains spampoison', lambda:test.re(br'spampoison', body))

    if route == '/robots.txt':
      test('reasonable robots.txt Cache-Control', lambda:test.notin('Expires', headers))
      test('reasonable robots.txt Cache-Control', lambda:test.eq(headers['Cache-Control'], 'max-age=15, must-revalidate'))

    if route == '/favicon.ico':
      #or TODO redirect? I guess I don't gain much with that, since
      # revalidation will be needed anyway and favicons aren't big
      # enough that it's worth cdn'ing them on top of the http 30x probably
      test('site has a favicon', lambda:test.eq(status_code, 200))

    # TODO check this better:
    test('vary accept-encoding', lambda:test.bool('Content-Encoding' not in headers or re.search(r'Accept-Encoding', headers['Vary'])))
    #if content_type in {'text/html', 'text/css', 'application/javascript'}:
    #nope they may have charset=, so.
    if re.search(r'text/html|text/css|application/javascript', content_type):
      test('vary accept-encoding', lambda:test.re(r'Accept-Encoding', headers['Vary']))
    #if content_type in {'image/png', 'image/jpeg'}:
    if re.search(r'image/png|image/jpeg', content_type):
      test('No Vary', lambda:test.notin('Vary', headers))

    

    return results

@asyncio.coroutine
def do_tests(config):
  with open(os.path.join(config.build_output_dir, 'build/nocdn-resource-routes'), 'r', encoding='utf-8') as f:
    # The transparent gif will never change meaning, so it's fine
    # as a well-known nigh-forever-cacheable name.
    config.tests_resource_routes = set(map(dedomain, f.read().split('\n'))) | {'/t.gif'}
  with open(os.path.join(config.build_output_dir, 'build/nonresource-routes'), 'r', encoding='utf-8') as f:
    config.tests_nonresource_routes = set(map(dedomain, f.read().split('\n')))

  config.tests_existent_routes = config.tests_resource_routes | config.tests_nonresource_routes
  config.tests_tested_routes = config.tests_existent_routes | set(config.test_status_codes)

  @asyncio.coroutine
  def test_route_here(route):
    return (yield from test_route(config, route))

  test_results = map(asyncio.Task, map(test_route_here, config.tests_tested_routes))

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

def test(config):
  c = do_tests(config)
  loop().run_until_complete(c)

def main():
  test('127.0.0.1', 80)
  #test('www.idupree.com', 80)

#if __name__ == '__main__':
#  main()


