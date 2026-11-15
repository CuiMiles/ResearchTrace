"""Inspect a user archive before isolated extraction; never execute its contents."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / 'evidence/competition-dataset'


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def prepare(archive):
    OUT.mkdir(exist_ok=True, parents=True)
    seven = ROOT / '.tools/archive-tools/root/usr/lib/7zip/7z'
    result = subprocess.run([str(seven), 'l', '-slt', str(archive)], check=True, capture_output=True, text=True)
    (OUT / 'archive-list.log').write_text(result.stdout)
    body = result.stdout.split('----------\n', 1)[1]
    entries = []
    for raw in body.strip().split('\n\n'):
        entry = dict(line.split(' = ', 1) for line in raw.splitlines() if ' = ' in line)
        if not entry:
            continue
        name = entry['Path']
        posix, windows = PurePosixPath(name), PureWindowsPath(name)
        if posix.is_absolute() or windows.is_absolute() or windows.drive or '..' in posix.parts or '..' in windows.parts or '\\' in name or ':' in name:
            raise ValueError('Unsafe archive path')
        if any(entry.get(k) for k in ('Symbolic Link', 'Hard Link', 'Copy Link')) or entry.get('Encrypted') != '-':
            raise ValueError('Links/encrypted archive entries are not supported')
        entries.append(entry)
    if len(entries) > 500 or sum(int(e.get('Size', 0)) for e in entries) > 2 * 1024 ** 3:
        raise ValueError('Archive inspection budget exceeded')
    sha = digest(archive)
    target = ROOT / 'evals/files' / ('user-dataset-' + sha[:12])
    if target.exists():
        raise ValueError('Refusing to overwrite an existing dataset directory')
    target.mkdir(parents=True, mode=0o700)
    env = dict(os.environ, LD_LIBRARY_PATH=str(ROOT / '.tools/archive-tools/root/usr/lib/x86_64-linux-gnu'))
    tar = ROOT / '.tools/archive-tools/root/usr/bin/bsdtar'
    result = subprocess.run([str(tar), '-xvf', str(archive), '-C', str(target), '--no-same-owner', '--no-same-permissions'],
                            env=env, capture_output=True, text=True, timeout=180)
    (OUT / 'extract.log').write_text(result.stdout + result.stderr)
    result.check_returncode()
    from pypdf import PdfReader
    files = []
    for entry in entries:
        path = target / entry['Path']
        if not path.resolve().is_relative_to(target.resolve()) or path.is_symlink():
            raise ValueError('Unsafe extracted path')
        if entry['Folder'] == '+':
            continue
        if not path.is_file() or path.stat().st_size != int(entry['Size']):
            raise ValueError('Incomplete extracted file')
        file_sha = digest(path)
        info = dict(id=file_sha[:16], name=path.name, relative_path=str(path.relative_to(target)), sha256=file_sha,
                    bytes=path.stat().st_size, kind=path.suffix.lstrip('.').lower())
        if path.suffix.lower() == '.pdf':
            reader = PdfReader(path)
            info.update(page_count=len(reader.pages), encrypted=reader.is_encrypted,
                        role='task_description' if path.parent == target else 'test_input')
        files.append(info)
    actual = [p for p in target.rglob('*') if p.is_file()]
    if len(files) != len(actual):
        raise ValueError('Unlisted extracted files')
    dataset = dict(id='user-' + sha[:12], label='科研小助手 · 用户提供原始资料包', source_name=archive.name,
                   archive_sha256=sha, archive_bytes=archive.stat().st_size,
                   extracted_root=str(target.relative_to(ROOT)), file_count=len(files), files=files,
                   source_note='用户提供的测试资料包；包含赛题点名文件。未独立验证发布渠道，不自动宣称组委会签名原包。')
    (OUT / 'manifest.json').write_text(json.dumps(dataset, ensure_ascii=False, indent=2))
    now = datetime.now(timezone.utc).isoformat()
    workflow = dict(dataset=dataset, test_execution_started=False, updated_at=now, steps=[dict(id='inventory', runs=[dict(
        id='extract-' + sha[:12], label='原包检查、隔离解压与文件登记', status='PASS', finished=now, summary=f'保留原包；安全解压 {len(files)} 个文件。页数核对仅用于清单，此时尚未开始功能测试。',
        files=files, counts={'files': len(files), 'pages': sum(f.get('page_count', 0) for f in files)},
        evidence_files=[{'path': f'evidence/competition-dataset/{p}'} for p in ('manifest.json', 'archive-list.log', 'extract.log')], screenshots=[],
        command='.venv/bin/python scripts/prepare_competition_dataset.py 科研小助手.rar')])])
    (OUT / 'workflow.json').write_text(json.dumps(workflow, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in dataset.items() if k != 'files'}, ensure_ascii=False))


if __name__ == '__main__':
    prepare(Path(sys.argv[1]).resolve())
