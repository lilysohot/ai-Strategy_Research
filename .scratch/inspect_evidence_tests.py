from pathlib import Path
import os,signal
for p in Path('/proc').iterdir():
 if not p.name.isdigit():continue
 try:args=(p/'cmdline').read_bytes().decode().split('\0')
 except (OSError,UnicodeError):continue
 if len(args)>3 and args[1:3]==['-m','pytest'] and 'tests/test_team_evidence_lifecycle.py' in args and len(args)>20:
  print('Interrupting expanded diagnostic pytest run',p.name,'files',len(args)-3)
  os.kill(int(p.name),signal.SIGINT)
