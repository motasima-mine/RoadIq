"""Run once to commit the cleanup of the temp git endpoint, then delete this file."""
import subprocess, os
p = os.path.join(os.path.dirname(__file__), '..')
subprocess.run(['git', 'add', 'server.py'], cwd=p)
r = subprocess.run(['git', 'commit', '-m', 'chore: remove temporary git snapshot endpoint'], cwd=p, capture_output=True, text=True)
print(r.stdout or r.stderr)
