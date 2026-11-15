"""Install only ResearchTrace's own user units. Does not touch nginx/DNS/services."""
import subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[1]
units=Path.home()/'.config/systemd/user'
units.mkdir(parents=True,exist_ok=True)
for name,module,memory,cpu in [('api','services.api.serve','512M','70%'),('worker','services.worker.main','896M','100%')]:
    path=units/f'researchtrace-{name}.service'
    expected=f'WorkingDirectory={root}'
    if path.exists() and expected not in path.read_text():
        raise SystemExit('Existing unit belongs to another checkout; stop for review')
    path.write_text(f'''[Unit]
Description=ResearchTrace {name}
After=network.target

[Service]
Type=simple
WorkingDirectory={root}
ExecStart={root}/.venv/bin/python -m {module}
Restart=on-failure
RestartSec=3
MemoryMax={memory}
CPUQuota={cpu}
Environment=OPENBLAS_NUM_THREADS=1
Environment=OMP_NUM_THREADS=1
Environment=MKL_NUM_THREADS=1
NoNewPrivileges=true
PrivateTmp=true
UMask=0077

[Install]
WantedBy=default.target
''')
subprocess.run(['systemctl','--user','daemon-reload'],check=True)
subprocess.run(['systemctl','--user','enable','--now','researchtrace-api.service','researchtrace-worker.service'],check=True)
print('ResearchTrace user services installed and started (API512M + worker896M limits).')
