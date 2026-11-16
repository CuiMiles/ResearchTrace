"""Install only ResearchTrace's own user units. Does not touch nginx/DNS/services."""
import subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[1]
units=Path.home()/'.config/systemd/user'
units.mkdir(parents=True,exist_ok=True)
units_to_install=[('api','services.api.serve','512M','70%'),('worker-documents','services.worker.main','896M','100%'),('worker-interactive','services.worker.main','384M','70%')]
legacy=units/'researchtrace-worker.service'
if legacy.exists():
    if f'WorkingDirectory={root}' not in legacy.read_text():
        raise SystemExit('Existing legacy worker belongs to another checkout; stop for review')
    subprocess.run(['systemctl','--user','disable','--now','researchtrace-worker.service'],check=True)
if (root/'.tools/paddle-env/bin/python').exists() or (root/'.tools/mineru-env/bin/python').exists():
    units_to_install.append(('parser','services.parsing.server','5G','200%'))
for name,module,memory,cpu in units_to_install:
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
Environment=RT_WORKER_POOL={name.removeprefix('worker-') if name.startswith('worker-') else 'all'}
NoNewPrivileges=true
PrivateTmp=true
UMask=0077

[Install]
WantedBy=default.target
''')
subprocess.run(['systemctl','--user','daemon-reload'],check=True)
subprocess.run(['systemctl','--user','enable','--now',*[f'researchtrace-{name}.service' for name,_,_,_ in units_to_install]],check=True)
print('ResearchTrace user services installed and started: '+', '.join(name+' '+memory for name,_,memory,_ in units_to_install)+'. Parser is optional; enhanced inference is outside lite memory target.')
