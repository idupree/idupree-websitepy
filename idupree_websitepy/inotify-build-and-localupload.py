
import subprocess, fcntl, os, os.path, time, datetime, sys
os.chdir(os.path.dirname(os.path.join('.', __file__)))
os.chdir('..')

p = subprocess.Popen(
  ['inotifywait', '-m', '-q', '-r', '.',
   '-e', 'modify', '-e', 'attrib', '-e', 'move', '-e', 'create', '-e', 'delete',
   r'--exclude=^\./\.git/|~$|\.(kate-swp|new|swp)$'],
  stdin=subprocess.PIPE,
  stdout=subprocess.PIPE
  )
p.stdin.close()
fd = p.stdout.fileno()
fl = fcntl.fcntl(fd, fcntl.F_GETFL)

def do_build():
  try:
    sys.stderr.write('building      '+datetime.datetime.today().isoformat(' ')+'\n')
    subprocess.check_call(['python3', 'aux/build.py'])
    sys.stderr.write('local deploy  '+datetime.datetime.today().isoformat(' ')+'\n')
    subprocess.check_call(['python3', 'priv/deploy.py', 'local'])
    sys.stderr.write('testing  '+datetime.datetime.today().isoformat(' ')+'\n')
    subprocess.check_call(['python3', 'aux/tests.py'])
    sys.stderr.write('done          '+datetime.datetime.today().isoformat(' ')+'\n\n')
  except subprocess.CalledProcessError as e:
    sys.stderr.write('FAILED ({:3})  '.format(e.returncode)+datetime.datetime.today().isoformat(' ')+'\n\n')

while True:
  do_build()
  fcntl.fcntl(fd, fcntl.F_SETFL, fl & ~os.O_NONBLOCK)
  os.read(fd, 1)
  fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
  # wait for any other instant changes that were coming along,
  # so that we won't have to rebuild right after we build
  time.sleep(0.08)    # 0.01)
  # clear out any messages that happen before we start building
  try:
    while True: os.read(fd, 1024)
  except BlockingIOError: pass

