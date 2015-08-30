#!/usr/bin/env python
import random

easy_to_read_and_type = '23456789abcdefghijkmnpqrstuvwxyz'
alnum = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
def alnum_secret(length = 22):
  """
  The default length of 22 gives at least 128 bits of entropy
  (entropy = log2(62**length))
  """
  rng = random.SystemRandom()
  return ''.join(rng.choice(alnum) for _ in range(length))

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

