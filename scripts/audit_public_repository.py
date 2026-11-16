"""Read-only prepublication check; reports paths/object IDs, never secret values."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import time

from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parents[1]
PATTERNS={
    'google_api_key':re.compile(rb'AIza[0-9A-Za-z_-]{35}'),
    'github_token':re.compile(rb'(?:gh[pousr]_[0-9A-Za-z]{30,}|github_pat_[0-9A-Za-z_]{35,})'),
    'private_key':re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'),
}


def known_secrets():
    values=set();config=dotenv_values(ROOT/'.env') if (ROOT/'.env').exists() else {}
    for name,value in config.items():
        if not value:continue
        if name.endswith('_FILE') and ('TOKEN' in name or 'SECRET' in name):
            path=Path(value)
            if path.is_file():values.add(path.read_bytes().strip())
        elif re.search(r'(?:KEY\d*|SECRET|TOKEN|PASSWORD|ACCESS_CODE|ADMIN_CODE)$',name) and len(value)>=8:
            values.add(value.encode())
    for path in (ROOT/'data').glob('*session*.json'):
        try:data=json.loads(path.read_text())
        except (OSError,ValueError):continue
        for key in ('cookie','access_code','token'):
            value=data.get(key)
            if isinstance(value,str) and len(value)>=8:values.add(value.encode())
    for path in (ROOT/'data').glob('*reviewer*.json'):
        try:data=json.loads(path.read_text())
        except (OSError,ValueError):continue
        for key in ('cookie','access_code'):
            value=data.get(key)
            if isinstance(value,str) and len(value)>=8:values.add(value.encode())
    return {value for value in values if len(value)>=8}


def scan(output):
    values=known_secrets();findings=[];oversized=[]
    paths=subprocess.check_output(['git','ls-files','-co','--exclude-standard','-z'],cwd=ROOT).split(b'\0')
    paths=sorted(set(p.decode() for p in paths if p))
    def inspect(data,location):
        if any(value in data for value in values):findings.append({'location':location,'rule':'configured_private_value'})
        for name,pattern in PATTERNS.items():
            if pattern.search(data):findings.append({'location':location,'rule':name})
    for name in paths:
        path=ROOT/name
        if not path.is_file():continue
        if path.stat().st_size>=95*1024**2:oversized.append(name)
        inspect(path.read_bytes(),{'path':name,'source':'worktree'})
        if path.name=='.env' or re.fullmatch(r'id_(rsa|ed25519|ecdsa)',path.name):
            findings.append({'location':{'path':name},'rule':'private_configuration_file'})
    lines=subprocess.check_output(['git','rev-list','--objects','HEAD'],cwd=ROOT).decode().splitlines()
    objects=[line.split(' ',1) for line in lines];blobs=0
    with subprocess.Popen(['git','cat-file','--batch'],cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE) as proc:
        for entry in objects:
            oid=entry[0];proc.stdin.write((oid+'\n').encode());proc.stdin.flush()
            header=proc.stdout.readline().decode().strip().split()
            if len(header)!=3:raise RuntimeError('Cannot inspect Git object')
            data=proc.stdout.read(int(header[2]));assert proc.stdout.read(1)==b'\n'
            if header[1]=='blob':
                blobs+=1;inspect(data,{'object':oid,'path':entry[1] if len(entry)>1 else None,'source':'reachable_history'})
        proc.stdin.close();assert proc.wait(timeout=10)==0
    report={'status':'PASS' if not findings and not oversized else 'FAIL','checked_at':time.time(),
            'scope':'Current tracked/untracked nonignored files plus every blob reachable from HEAD',
            'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'candidate_files':len(paths),'history_blobs':blobs,'configured_values_checked':len(values),
            'findings':findings,'oversized_files':oversized,'private_values_printed':False}
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False));return 0 if report['status']=='PASS' else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,default=ROOT/'evidence/review-upgrade/publication-audit.json')
    raise SystemExit(scan(parser.parse_args().output))
