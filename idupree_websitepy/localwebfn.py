
#from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
from http.server import BaseHTTPRequestHandler, HTTPServer
import webbrowser

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
