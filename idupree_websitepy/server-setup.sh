#!/bin/sh

# Run as root on an aspiring server.
#
# Given an Ubuntu installation (or Debian, or any distro on which you install
# OpenResty's build deps yourself), sets it up as an OpenResty server
# in a particular way.  OpenResty is built as the unprivileged user
# 'openrestybuild' and run as the unprivileged user 'openrestyuser'.
# Log files are currently unmanaged and go in /home/openrestyuser/prefix/ .
# /srv/openresty is 750 root:openrestyuser so that other users won't be
# able to see what's being served.

# Put server config under /srv/openresty/ and specifically nginx.conf at
#     /srv/openresty/conf/nginx.conf
# all readable but not writable by 'openrestyuser' (e.g. mode 755 root-owned).

# Start OpenResty using:
#     ulimit -n 50000; su - openrestyuser -c 'authbind /home/openrestybuild/inst/nginx/sbin/nginx -p /home/openrestyuser/prefix/ -c /srv/openresty/conf/nginx.conf'
# where 50000 is whatever OS-level open-file-descriptor limit
# you wish to set (rather than the default of 1024 which is rather low
# for a high performance web server).

# This script is idempotent (provided the state of the world is roughly
# as expected) and can be used on a running server to rebuild OpenResty
# (e.g. for a newer version, or for different configure flags,
# or just rebuilding it against newer system libraries).
# If OpenResty is running, it cleanly restarts it to run the new binary.
# Upgrading a running server (by compiling software on it, even!)
# is clearly never going to be as clean as replacing it with a new server.
# This script is only moderately careful about not breaking things.
#
# This script upgrades the system, but does not reboot it.
# This script asks interactively before upgrading system software so you can
# Ctrl-C if you don't like it; upgrading isn't critical to this script
# (but if you want to run the rest of the script without upgrading,
#  you will have to delete that command from the script).


# This was based on a similar Dockerfile I wrote that I'm not using
# because Docker 0.7 isn't mature enough (Docker developers state that
# Docker is not production-ready.  For specific examples that were issues
# for me, one couldn't yet send a signal to a container
#      https://github.com/dotcloud/docker/pull/2416
# and I didn't yet find a way in Docker docs to switch from one Docker
# container serving public port 80 to another without a moment of downtime
# on public port 80.  Also my kernel RAM usage grew and grew while playing
# with Docker until I shut it down, and /var/lib/docker stayed multi-gigabyte
# after deleting all containers and images and shutting down Docker and
# disabling Docker and rebooting [and looking for any other way to clear
# that usage besides rm -rf, or even for a way to find out what it was
# being used for].)


set -eux

# add 'universe' to Ubuntu repositories
# not necessary on DigitalOcean 12.04 and may need to be adapted for places where it is needed
# sed -Ei 's@^(deb http://(archive|security)\.ubuntu\.com/ubuntu '"$(lsb_release -sc)"'(|-updates|-security) main)$@\1 universe@' /etc/apt/sources.list
if which apt-get; then
  apt-get update
  apt-get upgrade
  apt-get install -y wget gnupg-curl build-essential libssl-dev libpcre3-dev authbind
fi

useradd -m openrestybuild || true
useradd -m openrestyuser || true

# ordinary users sometimes don't have sbin in PATH by default, so fix that.
# (For some reason nginx/openresty's build requires it even when it is
#  never once built, installed, or ran as root.)
if which ldconfig && su - openrestybuild -c '! which ldconfig'; then
  sed -Ei 's@^(ENV_(SU)?PATH[ \t]+PATH=).*$@\1/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin@' /etc/login.defs
fi

chmod 750 /home/openrestyuser
su - openrestyuser -c 'mkdir -p /home/openrestyuser/prefix/logs'

mkdir -p /srv/openresty
chmod 750 /srv/openresty
chown root:openrestyuser /srv/openresty

for port in 80 443; do
  touch /etc/authbind/byport/$port
  chmod 754 /etc/authbind/byport/$port
  chown root:openrestyuser /etc/authbind/byport/$port
done

# prefer building less-trusted software as a less-trusted user
_version=ngx_openresty-1.4.3.6
_flags='--with-luajit --with-http_spdy_module --with-ipv6'
su - openrestybuild -c "test -f ${_version}.tar.gz.asc || wget http://openresty.org/download/${_version}.tar.gz.asc"
su - openrestybuild -c "test -f ${_version}.tar.gz || wget http://openresty.org/download/${_version}.tar.gz"
su - openrestybuild -c "gpg --keyserver hkps://gpg.planetcyborg.de --keyserver-options ca-cert-file=/etc/ssl/certs/ca-certificates.crt --recv-keys 25451EB088460026195BD62CB550E09EA0E98066"
su - openrestybuild -c "gpg --verify ${_version}.tar.gz.asc ${_version}.tar.gz"
su - openrestybuild -c "rm -rf ${_version}"
su - openrestybuild -c "tar xzf ${_version}.tar.gz"
su - openrestybuild -c "cd ${_version} && ./configure ${_flags} --prefix=/home/openrestybuild/inst"
su - openrestybuild -c "cd ${_version} && make -j2"
su - openrestybuild -c "rm -rf /home/openrestybuild/inst-tmp2 /home/openrestybuild/inst-tmp1"
su - openrestybuild -c "cd ${_version} && make install DESTDIR=/home/openrestybuild/inst-tmp1"
su - openrestybuild -c "rm -rf ${_version}"
# atomic directory swap doesn't exist
# (unless/until this happens: https://lwn.net/Articles/569134/ , https://lkml.org/lkml/2014/1/8/650 )
su - openrestybuild -c "mv /home/openrestybuild/inst /home/openrestybuild/inst-tmp2 || true"
su - openrestybuild -c "mv /home/openrestybuild/inst-tmp1/home/openrestybuild/inst /home/openrestybuild/"
if test -e /home/openrestyuser/prefix/logs/nginx.pid; then
  # "Upgrade Executable on the fly" - http://wiki.nginx.org/CommandLine
  _oldpid="$(cat /home/openrestyuser/prefix/logs/nginx.pid)"
  kill -USR2 "$_oldpid"
  sleep 5
  kill -QUIT "$_oldpid"
  #Or?:
  #sleep 2
  #kill -WINCH "$_oldpid"
  #sleep 2
  #echo "Server still okay? If so, hit return; if not, hit Ctrl-C"
  #kill -QUIT "$_oldpid"
  #...else run the sequence to restore the old nginx process?
fi
su - openrestybuild -c "rm -rf /home/openrestybuild/inst-tmp2 /home/openrestybuild/inst-tmp1"

