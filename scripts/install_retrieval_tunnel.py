"""Install only this checkout's authenticated loopback retrieval tunnel."""
import os
from pathlib import Path
import re
import subprocess
from dotenv import load_dotenv

root=Path(__file__).resolve().parents[1];load_dotenv(root/'.env')
host=os.getenv('RT_RETRIEVAL_SSH_HOST','')
if not re.fullmatch(r'[A-Za-z0-9_@.-]{1,200}',host):raise SystemExit('Set the already authorized SSH host in private RT_RETRIEVAL_SSH_HOST')
path=Path.home()/'.config/systemd/user/researchtrace-retrieval-tunnel.service'
if path.exists() and f'WorkingDirectory={root}' not in path.read_text():raise SystemExit('Tunnel unit belongs to another checkout')
path.parent.mkdir(parents=True,exist_ok=True)
path.write_text(f'''[Unit]
Description=ResearchTrace private retrieval tunnel
After=network.target
[Service]
WorkingDirectory={root}
ExecStart=/usr/bin/ssh -N -T -o BatchMode=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval=20 -o ServerAliveCountMax=3 -L 127.0.0.1:18985:127.0.0.1:18985 -L 127.0.0.1:18986:127.0.0.1:18986 -L 127.0.0.1:18987:127.0.0.1:7890 {host}
Restart=on-failure
RestartSec=5
MemoryMax=96M
NoNewPrivileges=true
UMask=0077
[Install]
WantedBy=default.target
''')
subprocess.run(['systemctl','--user','daemon-reload'],check=True)
subprocess.run(['systemctl','--user','enable','--now',path.name],check=True)
import socket
import time
for _ in range(40):
    try:
        with socket.create_connection(('127.0.0.1',18985),timeout=.2):break
    except OSError:time.sleep(.25)
else:raise SystemExit('Tunnel has not started; inspect this project unit log')
print('ResearchTrace loopback tunnel installed; no remote public inference port.')
