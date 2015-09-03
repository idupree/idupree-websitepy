#!/usr/bin/env python3

# working from https://github.com/pypa/sampleproject
from setuptools import setup, find_packages
import sys

#from codecs import open
#from os import path
#here = path.abspath(path.dirname(__file__))
#with open(path.join(here, 'DESCRIPTION.rst'), encoding='utf-8') as f:
#  long_description = f.read()

#assert(sys.version_info[:2] >= (3,3))
assert(sys.version_info >= (3,3))

setup(
    name='idupree-websitepy',
    version='1.0.0',
    description="libraries for building idupree's website",
    url='https://github.com/idupree/idupree-websitepy',
    author='idupree',
    author_email='antispam@idupree.com',
    license='MIT',
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'License :: OSI Approved :: MIT License',
        'Natural Language :: English',
        'Operating System :: POSIX',
        'Topic :: Software Development :: Build Tools',
        'Topic :: Internet :: WWW/HTTP :: Site Management',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3 :: Only',
        'Programming Language :: Python :: 3.3',
        'Programming Language :: Python :: 3.4',
    ],
    keywords='',
    packages=find_packages(exclude=['contrib', 'docs', 'tests*']),
    install_requires=(
        ['http-parser'] +
        (['asyncio'] if sys.version_info < (3,4) else [])
    ),
    data_files=[],
)

