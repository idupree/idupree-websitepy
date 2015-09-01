
import subprocess, fcntl, os, os.path, time, datetime, sys

def inotify_daemon(
        function_to_run_on_change,
        files_and_directories_to_watch
        ):
  """
  Never returns (unless by exception thrown by the function).

  Calls function_to_run_on_change() whenever something
  in/under files_and_directories_to_watch changes.

  files_and_directories_to_watch is passed as inotifywait
  command-line arguments, so it can contain e.g.
  r'--exclude=^\./\.git/|~$|\.(kate-swp|new|swp)$'
  """
  p = subprocess.Popen(
    ['inotifywait', '-m', '-q', '-r',
     '-e', 'modify', '-e', 'attrib', '-e', 'move', '-e', 'create', '-e', 'delete',
     ] + list(files_and_directories_to_watch),
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE
    )
  p.stdin.close()
  fd = p.stdout.fileno()
  fl = fcntl.fcntl(fd, fcntl.F_GETFL)

  while True:
    function_to_run_on_change()
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


