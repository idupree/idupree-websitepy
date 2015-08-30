#!/usr/bin/env python
import random

from .utils import alnum_secret

def main():
  for k, v in (
      # 'unused' one in case the contents of secrets.py are hashed
      # somewhere and someone knows all but one of the other secrets
      # and uses that to brute-force the last one.  At the beginning
      # and the end for extra paranoia.
      ('unused_random_string_1', alnum_secret()),
      # this is not really random bytes, but who cares
      ('rr_hash_random_bytes', alnum_secret().encode('ascii')),
      ('nginx_hash_random_bytes', alnum_secret().encode('ascii')),
      ('errdocs_random_string', alnum_secret()),
      ('apache_random_query_string_1', alnum_secret()),
      ('apache_random_query_string_2', alnum_secret()),
      ('unused_random_string_2', alnum_secret())):
    print(k+' = '+repr(v))

if __name__ == '__main__':
  main()

