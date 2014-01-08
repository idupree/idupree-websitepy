
# See RFC 3986 and http://url.spec.whatwg.org/

# These *_*set variables are suitable for putting inside
# a regex's [...] or [^...] set (and not suitable for much else).
nonurl_byteset = br'\0- "<>\\^`|{}\177'
nonurl_charset = nonurl_byteset.decode()
urlbyte = br'[^'+nonurl_byteset+br']'
urlbytes = urlbyte + br'+'
# this wrongly excludes non-ASCII characters ( see http://url.spec.whatwg.org/#url-code-points );
# listing out the alphabet rather than a-zA-Z0-9 so that locale doesn't affect it:
#urlchar = r"""[ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789\-._~:/?#[\]@!$&'()*+,;=%]"""
urlchar = r'[^'+nonurl_charset+r']'
nonurlchar = r'['+nonurl_charset+r']'
urlchar_sans_single_quote = r'[^'+nonurl_charset+r"']"
urlchar_sans_parentheses = r'[^'+nonurl_charset+r'()]'
schemechar = r"""[ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789\-+.]"""
# These are to be applied to strings that already match urlchar* :
urlwithdomain = r'^//|^' + schemechar + r'+:'
domainrelativeurl = r'^/$|^/[^/]'
samepageurl = r'^#|^$'
# clearlydirectoryurl: path ends in any of / . ..
clearlydirectoryurl = r'^[^?#]*(?:/|(^|/)\.\.?)(?:[?#]|$)'

# likely ext: ends in .alphanumeric with at least one non-numeric character
extension = r""".\.[ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789]*[ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz][ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789]*$"""


