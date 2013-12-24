
# Character-based REs are listing out the alphabet rather than a-zA-Z0-9 so that locale doesn't affect them.
# see RFC 3986
urlbyte = br'[^\0- "<>\\^{}\177]'
urlbytes = urlbyte + br'+'
urlchar = br"""[ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789\-._~:/?#[\]@!$&'()*+,;=]"""
schemechar = br"""[ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789\-+.]"""
# These are to be applied to strings that already match urlchar* :
urlwithdomain = br'^//|^' + schemechar + br'+:'
domainrelativeurl = br'^/$|^/[^/]'
samepageurl = br'^#|^$'
clearlydirectoryurl = br'/$|(^|/)\.\.?$'  #uh what if the trailing slash is in a ? or # part? hm.

# likely ext: ends in .alphanumeric with at least one non-numeric character
extension = br""".\.[ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789]*[ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz][ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789]*$"""


