
import sys

class HttpErr(object):
  def __init__(self, code, desc, retryable=False):
    self.code = code
    self.string = str(code) + ' ' + desc
    self.retryable = retryable

errdocErrs = [
  HttpErr(code=400, desc='Bad Request'),
  HttpErr(code=401, desc='Unauthorized'),
  HttpErr(code=403, desc='Forbidden'),
  HttpErr(code=404, desc='Not Found'),
  HttpErr(code=405, desc='Method Not Allowed'),
  HttpErr(code=406, desc='Not Acceptable'),
  HttpErr(code=408, desc='Request Timeout', retryable=True),
  HttpErr(code=410, desc='Gone'),
  HttpErr(code=411, desc='Length Required', retryable=True),
  HttpErr(code=412, desc='Precondition Failed'),
  HttpErr(code=413, desc='Request Entity Too Large'),
  HttpErr(code=414, desc='Request-URI Too Long'),
  HttpErr(code=415, desc='Unsupported Media Type'),
  HttpErr(code=416, desc='Requested Range Not Satisfiable'),
  HttpErr(code=417, desc='Expectation Failed'),
  HttpErr(code=500, desc='Internal Server Error', retryable=True),
  HttpErr(code=501, desc='Not Implemented'),
  HttpErr(code=502, desc='Bad Gateway'),
  HttpErr(code=503, desc='Service Unavailable', retryable=True),
  HttpErr(code=504, desc='Gateway Timeout', retryable=True),
  HttpErr(code=505, desc='HTTP Version Not Supported'),
]
errdocErrsByCode = {e.code: e for e in errdocErrs}
errdocCodes = tuple(e.code for e in errdocErrs)

def errdoc(err):
  """
  err: HttpErr or numeric code
  returns: string (HTML document, self-contained)
  """
  if isinstance(err, int): err = errdocErrsByCode[err]
  return ("""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<meta name="robots" content="noindex, noarchive, nosnippet" />
<title>"""+err.string+"""</title>
<style>
html,body{
color:#000000;
background-color:#aaddff;
}

html,body,div,h1,p,a{
margin:0;padding:0;border:0;
font:36px bold;
font-family: "Lucida Sans Unicode", "Lucida Grande", serif;
text-align:center;
}

html,body,#d1 {height:100%;width:100%;}
#d1 {display:table;}
#d2 {display:table-cell;vertical-align:middle;}

#d3 {
        background-color: #ffddaa;
        padding: 10px 20px;
        display:inline-block;
}

h1 {color:#ff4444;}
p,a {color:#008800;}
</style>
</head>
<body>
<div id="d1"><div id="d2"><div id="d3">
"""+(
"""<div id="retry"></div>
<script>document.getElementById('retry').innerHTML =
        '<p id="retry"><a href="javascript:location.reload(true)">Try again?</a></p>';</script>
""" if err.retryable else ""
)+"""<h1>"""+err.string+"""</h1>
<p><a href="/">Return to idupree.com</a></p>
</div></div></div>
</body>
</html>
""")

def main():
  if len(sys.argv) == 2 and sys.argv[1] != '--help':
    if sys.argv[1] == 'codes':
      sys.stdout.write('\n'.join(map(str, errdocCodes)))
    else:
      sys.stdout.write(errdoc(int(sys.argv[1])))
  else:
    sys.stderr.write((
       """{argv0} codes\n  output all codes this script makes an errdoc for, one per line\n"""
      +"""{argv0} <code>\n  where code can be {codes}\n""").format(
      argv0=sys.argv[0],
      codes=', '.join(map(str, errdocCodes))))


if __name__ == "__main__":
  main()

