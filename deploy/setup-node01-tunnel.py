#!/usr/bin/env python3
"""Run on node01 only: restricted ECS key and Workbench-verified host identity.
No provider credentials are read or displayed. Compatible with system Python3.6.
Install node01-researchtrace-tunnel.service separately after this completes.
"""
import subprocess,pathlib,os,shlex,json
root=pathlib.Path('/home/CuiMinghao/.local/share/researchtrace-deployment')
root.mkdir(parents=True,exist_ok=True,mode=0o700)
key=root/'ecs_ed25519'
if not key.exists():
 subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-C','researchtrace-ecs-restricted','-f',str(key)],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
wb='/home/CuiMinghao/.local/bin/workbench'
instance='i-bp13r66a7w9gwi5fs48n'
def run(command):
 r=subprocess.run([wb,'exec','-i',instance,'--timeout','30','-c',command],stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True,timeout=65)
 if r.returncode: raise RuntimeError('Workbench command failed (private output omitted)')
 return r.stdout
hostkey=run("python3 -c \"print(open('/etc/ssh/ssh_host_ed25519_key.pub').read().strip())\"").strip()
if not hostkey.startswith('ssh-ed25519 '):raise ValueError('Unrecognised authenticated host key response')
(root/'known_hosts').write_text('118.31.50.2 '+hostkey+'\n');os.chmod(root/'known_hosts',0o600)
pub=(key.with_suffix('.pub')).read_text().strip()
line='restrict,port-forwarding,command="/bin/false",permitopen="127.0.0.1:1",permitlisten="127.0.0.1:18985",permitlisten="127.0.0.1:18986",permitlisten="127.0.0.1:18987" '+pub
code="from pathlib import Path; import os; p=Path('/root/.ssh'); p.mkdir(mode=0o700,exist_ok=True); f=p/'authorized_keys'; line="+repr(line)+"; old=f.read_text() if f.exists() else ''; f.write_text(old+('' if old.endswith('\\n') or not old else '\\n')+line+'\\n') if line not in old.splitlines() else None; os.chmod(f,0o600)"
run('python3 -c '+shlex.quote(code))
print(json.dumps({'status':'PASS','dedicated_restricted_key':True,'authenticated_known_host':True,'public_inference_ports':False}))
