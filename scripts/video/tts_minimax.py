"""MiniMax speech synthesis for the walkthrough, one call per group of lines.
Usage: python3 tts_minimax.py narration_v3.json OUTDIR [group ...]
The key is read from ~/projects/MiniMax/.env and never printed or written."""
import json, os, sys, time, binascii
import requests
HOST = 'https://api.minimax.chat'
def key():
    for line in open(os.path.expanduser('~/projects/MiniMax/.env'), encoding='utf-8'):
        if '=' in line and line.split('=', 1)[0].strip() == 'MINIMAX_API_KEY':
            return line.split('=', 1)[1].strip().strip('"\'')
    raise SystemExit('no key')
spec = json.load(open(sys.argv[1], encoding='utf-8')); out = sys.argv[2]; want = {int(g) for g in sys.argv[3:]}
os.makedirs(out, exist_ok=True); K = key(); voice = spec['voice']
http = requests.Session(); http.trust_env = False  # direct: the China endpoint needs no proxy
groups = {}
for sc in spec['scenes']:
    groups.setdefault(sc['group'], []).append(sc)
ledger = open(os.path.join(out, 'attempts.jsonl'), 'a', encoding='utf-8')
for g in sorted(groups):
    if want and g not in want: continue
    parts = []
    for i, sc in enumerate(groups[g]):
        if i: parts.append('<#0.7#>')
        parts.append('<#0.4#>'.join(l.get('say', l['sub']) for l in sc['lines']))
    text = ''.join(parts)
    body = {'model': voice['model'], 'text': text, 'stream': False, 'language_boost': 'Chinese', 'output_format': 'hex',
            'voice_setting': {'voice_id': voice['voice_id'], 'speed': voice['speed'], 'vol': 1, 'pitch': 0},
            'audio_setting': {'sample_rate': 32000, 'bitrate': 128000, 'format': 'mp3', 'channel': 1},
            'subtitle_enable': True}
    meta = {'group': g, 'chars': len(text), 'model': voice['model'], 'voice': voice['voice_id'], 'time': time.time()}
    t = time.time()
    try:
        r = http.post(HOST + '/v1/t2a_v2', json=body, headers={'Authorization': 'Bearer ' + K}, timeout=180)
        meta['http'] = r.status_code
        d = r.json()
        base = d.get('base_resp') or {}
        meta['code'] = base.get('status_code'); meta['msg'] = str(base.get('status_msg', ''))[:160]
        meta['trace'] = d.get('trace_id')
        info = d.get('extra_info') or {}
        meta['audio_ms'] = info.get('audio_length'); meta['usage_characters'] = info.get('usage_characters')
        data = d.get('data') or {}
        if meta['code'] == 0 and data.get('audio'):
            open(os.path.join(out, 'g%02d.mp3' % g), 'wb').write(binascii.unhexlify(data['audio']))
            sub = data.get('subtitle_file')
            if sub:
                s = http.get(sub, timeout=60); meta['subtitle_http'] = s.status_code
                open(os.path.join(out, 'g%02d.subtitle.json' % g), 'wb').write(s.content)
            meta['status'] = 'ok'
        else:
            meta['status'] = 'failed'
    except Exception as e:
        meta['status'] = 'error'; meta['error'] = type(e).__name__
    meta['seconds'] = round(time.time() - t, 1)
    ledger.write(json.dumps(meta, ensure_ascii=False) + '\n'); ledger.flush()
    print(json.dumps(meta, ensure_ascii=False), flush=True)
    if meta['status'] != 'ok': break
    time.sleep(4)
