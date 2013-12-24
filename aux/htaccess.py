import re, sys
import errdocs
import secrets

def main():
  sys.stdout.write(htaccess)

#deleting comments probably speeds up Apache reading the file on every request(?)
def _delete_comments(s):
  return re.sub(r'^#.*\n', r'', s, flags=re.MULTILINE)

htaccess = _delete_comments("""
""" + '\n'.join('ErrorDocument {code} /err-{secret}/{code}.htm'
                    .format(code=code, secret=secrets.errdocs_random_string)
                for code in errdocs.errdocCodes) +
"""
# Various potentially relevant info:
# https://members.nearlyfreespeech.net/wiki/HowTo/GzipStatic
# http://bytes.com/topic/javascript/answers/589352-mimetype-text-javascript-obsolete

AddCharset utf-8 .html .htm .css .js .txt

# I want these headers to be set even for error responses, but why
# is that happening? The default is 'onsuccess' not 'always' according to
# https://httpd.apache.org/docs/current/mod/mod_headers.html
Header set X-Robots-Tag "noarchive"
# https://developer.mozilla.org/en/The_X-FRAME-OPTIONS_response_header
Header append X-Frame-Options "SAMEORIGIN"

# If I have a more dynamic web application I might go for the
# slightly greater system security of SymLinksIfOwnerMatch only
# at the expense of slight performance.
#
# No other options - no Indexes or MultiViews or anything
# - if they make a difference, I don't want them here!
DirectoryIndex
AcceptPathInfo Off
Options FollowSymLinks
RewriteEngine on

# Let the canonical domain be
# 'http://www.idupree.com', not 'http://idupree.com'.
#
# Put this rule near the beginning of the file in case that makes
# the redirect happen faster (after all, the new request is going to
# have to load and go through all these rules *anyway*...).
#
# This rule may need revising if I ever get SSL
# (because it is worded to redirect to 'http:'.  But then
# again SSL certificates are only valid for a certain exact
# domain, so it would need some thought regardless :-)
RewriteCond %{HTTP_HOST} ^idupree\.com|idupreecom\.nfshost\.com$ [NC]
RewriteRule ^(.*)$ http://www.idupree.com/$1 [R=301,L]

#canonical local-testing-domain, so the later rules don't have to care
RewriteCond %{HTTP_HOST} ^127\.0\.0\.1|\[::1\]|east$ [NC]
RewriteRule ^(.*)$ http://localhost/$1 [R=303,L]

# It's irritating that e.g. localhost///////// is valid and not a redirect,
# but I have rel="canonical", and Apache doesn't seem to have a good way
# to do anything different (if you know one, please tell me?).

RewriteCond %{HTTP_HOST} ^(?:www\.)?idupree\.com$ [NC]
RewriteRule ^robots\.txt$ official.robots.txt [L]

RewriteCond %{HTTP_HOST} ^localhost$ [NC]
RewriteRule ^robots\.txt$ local.robots.txt [L]

#Otherwise, default to the no-robots-allowed robots.txt.
#(e.g. any other testing locations and accidental circumstances.)

# Make some testing locations slightly less self-revealing:
RewriteCond %{HTTP_HOST} !^(?:www\.)?idupree\.com$ [NC]
RewriteRule ^testhomme$ index.html?"""+secrets.apache_random_query_string_1+"""=1 [L,QSA]

RewriteCond %{HTTP_HOST} !^(?:www\.)?idupree\.com|localhost$ [NC]
RewriteRule ^$ blank.html?"""+secrets.apache_random_query_string_1+"""=1 [L,QSA]

# If we would like to serve a path that's given to us with a trailing slash
# as a trailing-slash-less URL, then HTTP-redirect to there.
RewriteCond %{REQUEST_FILENAME}.html -f
RewriteRule ^(.*)/$ /$1 [R=301,L]

# Serve */index.html as */ (and only as */, and [R] * -> */ : See other rules
#                                                       and DirectorySlash.)
RewriteCond %{REQUEST_FILENAME}/index.html -f
RewriteRule (^|/)$ %{REQUEST_FILENAME}/index.html?"""+secrets.apache_random_query_string_1+"""=1 [QSA]


#Serve *.html's as * (and only as *: See later rule.)
RewriteCond %{REQUEST_FILENAME} !((^|/)index$)
RewriteCond %{REQUEST_FILENAME}.html -f
RewriteRule ^.*$ %{REQUEST_FILENAME}.html?"""+secrets.apache_random_query_string_1+"""=1 [QSA]

#Don't serve *.html's as *.html.
#(This comes after the "Serve *.html's as *" rule so that foo.html.html
#will serve as exactly "foo.html" :-)
RewriteCond %{REQUEST_FILENAME} !^/_resources/
RewriteCond %{QUERY_STRING} !"""+secrets.apache_random_query_string_1+"""
RewriteRule \.html$ letsHaveA404Error [NS]

# Directories that don't have an index should not be redirected
# to with-slash, or 403 forbidden, or anything of the sort.
# I'm not trying to serve them as anything, so they're a 404!
RewriteCond %{REQUEST_FILENAME} -d
RewriteCond %{REQUEST_FILENAME}/index.html !-f
RewriteRule ^.*$ letsHaveA404Error [NS]

DirectorySlash Off
RewriteCond %{REQUEST_FILENAME} -d
RewriteCond %{REQUEST_FILENAME}/index.html -f
RewriteRule ^(.*)$ /$1/ [R=301,L]

# Both spellings are cool with me! Let people who type it be happy.
Redirect permanent /four-colour /four-color
# In case people don't know which spelling of "mote"
Redirect permanent /spinmoat /spinmote


AddEncoding gzip .gzipped
<FilesMatch "\.gzipped$">
Header set Vary Accept-Encoding
</FilesMatch>

RewriteCond %{REQUEST_FILENAME} !^/_resources/
RewriteCond %{QUERY_STRING} !"""+secrets.apache_random_query_string_2+"""
RewriteRule \.gzipped$ letsHaveA404Error [NS]

# This rule goes *after* all redirects, so that this path isn't exposed to end users.
# Both wget and vows don't understand(don't unzip) gzip-encoded content, so
# this rule was quite thoroughly exercised!
RewriteCond %{HTTP:Accept-Encoding} gzip
RewriteCond %{QUERY_STRING} !"""+secrets.apache_random_query_string_2+"""
RewriteCond %{REQUEST_FILENAME}.gzipped -f
RewriteRule ^(.*)$ /$1.gzipped?"""+secrets.apache_random_query_string_2+"""=1 [QSA]


# Close enough: I just need to have no other 't.gif' files
# in other dirs than /
# My tests would probably catch me if I did that.
# (the Expires/Cache-Control tests).
<Files t.gif>
ExpiresActive On
ExpiresDefault "access plus 33 days"
ExpiresByType image/gif "access plus 33 days"
</Files>
# ..this is an even ickier condition. oh well.
<FilesMatch '^([a-z]*\.)?robots\.txt$'>
Header set Cache-Control "max-age=15, must-revalidate"
</FilesMatch>
""")

if __name__ == "__main__":
  main()
