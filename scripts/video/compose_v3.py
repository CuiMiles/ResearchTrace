"""Compose the v3 walkthrough: recorded frames + MiniMax narration + burned subtitles.
Outputs (in v3/out): researchtrace-demo-v4-1080p.mp4 (H.264/AAC, burned subtitles), .webm (VP8/Opus), .srt, .vtt, poster."""
import json, os, re, subprocess, sys
SP = os.environ.get('RT_VIDEO_WORK', '/tmp/rt-video')
F = f'{SP}/v3'; O = f'{F}/out'; os.makedirs(O, exist_ok=True)
TL = json.load(open(f'{F}/timeline.json')); TOTAL = TL['duration']
FPS = 30

# 1. Frame list for the concat demuxer: each recorded frame lasts until the next one, clipped to the scene.
entries = []
for sc in TL['scenes']:
    idx = json.load(open(f'{F}/scenes/{sc["id"]}/index.json')); dur = sc['end'] - sc['start']
    times = idx['times']; files = [f'{F}/scenes/{sc["id"]}/{n:05d}.jpg' for n in range(len(times))]
    keep = [(max(0.0, t), f) for t, f in zip(times, files) if t < dur]
    for k, (t, f) in enumerate(keep):
        nxt = keep[k + 1][0] if k + 1 < len(keep) else dur
        if nxt - t > 1e-4: entries.append((f, nxt - t))
with open(f'{O}/frames.txt', 'w') as fh:
    for f, d in entries: fh.write(f"file '{f}'\nduration {d:.4f}\n")
    fh.write(f"file '{entries[-1][0]}'\n")
print('frames', len(entries), 'video seconds', round(sum(d for _, d in entries), 2), 'timeline', TOTAL)

# 2. Subtitles: manual two-row wrapping (libass does not wrap CJK), bottom box; the typing scene uses the top.
def width(s): return sum(1 if ord(ch) > 0x2E7F else .55 for ch in s)
def wrap(s, limit=27):
    if width(s) <= limit: return [s]
    best = None; half = width(s) / 2
    for i, ch in enumerate(s):
        if ch in '，。；：、？！,;' and 0 < i < len(s) - 1:
            a, b = s[:i + 1], s[i + 1:]
            if width(a) <= limit + 3 and width(b) <= limit + 3:
                score = abs(width(a) - half)
                if best is None or score < best[0]: best = (score, [a, b.strip()])
    if best: return best[1]
    cut = 0; acc = 0
    for i, ch in enumerate(s):
        acc += width(ch)
        if acc > half: cut = i; break
    return [s[:cut], s[cut:].strip()]
def ts(t, sep='.'):
    h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60
    return f'{h}:{m:02d}:{s:05.2f}' if sep == '.' else f'{h:02d}:{m:02d}:{int(s):02d},{int(round((s - int(s)) * 1000)):03d}'
lines = [(sc['id'], l) for sc in TL['scenes'] for l in sc['lines']]
cues = []
for k, (sid, l) in enumerate(lines):
    nxt = lines[k + 1][1]['start'] if k + 1 < len(lines) else TOTAL
    end = min(l['end'] + .45, nxt - .05)
    cues.append((sid, l['start'], end, wrap(l['sub'])))
ass = ['[Script Info]', 'ScriptType: v4.00+', 'PlayResX: 1920', 'PlayResY: 1080', 'WrapStyle: 2', 'ScaledBorderAndShadow: yes', '',
       '[V4+ Styles]',
       'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding',
       'Style: Sub,Noto Sans CJK SC Medium,46,&H00FFFFFF,&H00FFFFFF,&H33141210,&H33141210,0,0,0,0,100,100,0.5,0,4,16,0,2,120,120,92,1',
       'Style: Mid,Noto Sans CJK SC Medium,46,&H00FFFFFF,&H00FFFFFF,&H33141210,&H33141210,0,0,0,0,100,100,0.5,0,4,16,0,2,120,120,250,1',
       'Style: Chip,Noto Sans CJK SC Medium,32,&H000E0C0B,&H00FFFFFF,&H003AF2C9,&H003AF2C9,0,0,0,0,100,100,0,0,4,12,0,9,60,60,46,1',
       '', '[Events]', 'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text']
for sid, a, b, rows in cues:
    ass.append(f'Dialogue: 0,{ts(a)},{ts(b)},{"Mid" if sid == "ask" else "Sub"},,0,0,0,,' + r'\N'.join(rows))
ans = next(s for s in TL['scenes'] if s['id'] == 'answer')
ass.append(f'Dialogue: 1,{ts(ans["start"])},{ts(ans["start"] + 2.6)},Chip,,0,0,0,,' + r'{\fad(200,300)}▶▶ 快进 · 回答已生成')
open(f'{O}/subs.ass', 'w', encoding='utf-8').write('\n'.join(ass) + '\n')
srt = []; vtt = ['WEBVTT', '']
for n, (sid, a, b, rows) in enumerate(cues, 1):
    srt += [str(n), f'{ts(a, ",")} --> {ts(b, ",")}', '\n'.join(rows), '']
    vtt += [f'{ts(a, ",").replace(",", ".")} --> {ts(b, ",").replace(",", ".")}', '\n'.join(rows), '']
open(f'{O}/researchtrace-demo-v4-zh.srt', 'w', encoding='utf-8').write('\n'.join(srt))
open(f'{O}/researchtrace-demo-v4-zh.vtt', 'w', encoding='utf-8').write('\n'.join(vtt))

if '--subs-only' in sys.argv: sys.exit(0)
# 3. Encode.
mp4 = f'{O}/researchtrace-demo-v4-1080p.mp4'
subprocess.check_call(['ffmpeg', '-y', '-v', 'error', '-stats', '-f', 'concat', '-safe', '0', '-i', f'{O}/frames.txt', '-i', f'{F}/narration.wav',
    '-vf', f"fps={FPS},scale=1920:1080:flags=lanczos,format=yuv420p,ass={O}/subs.ass", '-t', f'{TOTAL:.3f}',
    '-c:v', 'libx264', '-preset', 'slow', '-crf', '21', '-maxrate', '3M', '-bufsize', '6M', '-profile:v', 'high', '-level', '4.1', '-g', '60',
    '-c:a', 'aac', '-b:a', '160k', '-ar', '48000', '-movflags', '+faststart', mp4])
webm = f'{O}/researchtrace-demo-v4-1080p.webm'
subprocess.check_call(['ffmpeg', '-y', '-v', 'error', '-stats', '-i', mp4, '-map', '0:v:0', '-map', '0:a:0', '-c:v', 'libvpx', '-deadline', 'good', '-cpu-used', '4', '-threads', '8',
    '-crf', '12', '-b:v', '1600k', '-maxrate', '2400k', '-bufsize', '4800k', '-g', '90', '-pix_fmt', 'yuv420p', '-c:a', 'libopus', '-b:a', '96k', webm])
# Poster: the finished title card as recorded, without a subtitle plate.
cidx = json.load(open(f'{F}/scenes/cover/index.json'))['times']
subprocess.check_call(['ffmpeg', '-y', '-v', 'error', '-i', f'{F}/scenes/cover/{len(cidx) - 1:05d}.jpg', '-q:v', '3', f'{O}/researchtrace-demo-v4-poster.jpg'])
for f in (mp4, webm):
    print(os.path.basename(f), subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration,size,bit_rate', '-of', 'csv=p=0', f]).decode().strip())
