"""Assemble the timed ResearchTrace walkthrough from captured screens and TTS."""
import argparse
import json
import subprocess
import tempfile
import wave
from concurrent.futures import ThreadPoolExecutor
from itertools import pairwise
from pathlib import Path

FPS = 30
WIDTH, HEIGHT = 1920, 1080
RATE = 24000

# Local speech recognition and waveform inspection of the recorded TTS takes.
# Coordinates include the extra instruction read before each take.
STARTS = {
    0: [5.13, 11.37, 18.48, 23.34, 31.05],
    5: [4.86, 11.79, 20.70, 26.85, 34.20],
    10: [4.08, 11.28, 19.92, 25.47, 29.37],
    15: [5.13, 10.92, 14.16, 21.54, 31.26],
    20: [4.77, 11.70, 16.86, 23.52, 29.58],
    25: [4.32, 8.82, 14.40, 20.73, 27.15],
    30: [4.35, 11.70, 15.54, 21.00, 27.69],
    35: [4.62, 10.86, 18.48, 22.62, 29.13],
    45: [5.04, 12.84, 18.63, 25.77, 31.80],
    50: [4.53],
}
# Where the screen changes during the corresponding narration sentence.
# Each tuple is (fraction of sentence, captured frame, optional recording).
SHOTS = {
    0: [(0, 'opening-0', '')],
    2: [(0, 'cover-0', '')],
    3: [(0, 'library-0', '')],
    5: [(0, 'version-0', 'version')],
    8: [(0, 'revision-0', 'version')],
    9: [(0, 'revision-1', 'version')],
    10: [(0, 'revision-2', 'version')],
    11: [(0, 'reader-0', 'reader')],
    14: [(0, 'reader-1', 'reader')],
    15: [(0, 'selection-0', ''), (.32, 'selection-1', 'selection')],
    16: [(0, 'scan-0', 'scan')],
    19: [(0, 'book-0', '')],
    20: [(0, 'book-1', 'book'), (.48, 'book-2', 'book')],
    21: [(0, 'answer-0', '')],
    25: [(0, 'answer-1', 'answer')],
    26: [(0, 'cross-0', '')],
    27: [(0, 'cross-1', 'cross')],
    28: [(0, 'agent-0', '')],
    30: [(0, 'discover-0', '')],
    32: [(0, 'graph-0', '')],
    34: [(0, 'writing-0', '')],
    35: [(0, 'writing-1', '')],
    36: [(0, 'chart-0', '')],
    37: [(0, 'pipeline-0', '')],
    39: [(0, 'models-0', '')],
    42: [(0, 'metrics-0', '')],
    45: [(0, 'engineering-0', '')],
    46: [(0, 'engineering-1', '')],
    47: [(0, 'deploy-0', '')],
    49: [(0, 'close-0', '')],
    50: [(0, 'closing-0', '')],
}


def ffmpeg(*args, capture=False):
    result = subprocess.run(
        ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', *map(str, args)],
        check=True, stdout=subprocess.PIPE if capture else None,
    )
    return result.stdout


def read_frames(path):
    with wave.open(str(path), 'rb') as source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (1, 2, RATE):
            raise ValueError(f'Incompatible narration WAV: {path.name}')
        return source.readframes(source.getnframes())


def assemble_voice(root, output):
    original = read_frames(root / 'narration_cut.wav')
    first_take = json.loads(json.loads((root / 'lines.json').read_text())['text'])
    trim = json.loads((root / 'result.json').read_text())['seconds'] - len(original) / (2 * RATE)
    cues, count = [], 0
    with wave.open(str(output), 'wb') as destination:
        destination.setparams((1, 2, RATE, 0, 'NONE', 'not compressed'))
        for start in range(0, len(first_take), 5):
            if start in STARTS:
                source = read_frames(root / 'segments' / f'line-{start:02d}.wav')
                begin = STARTS[start][0] - .16
                end = len(source) / (2 * RATE)
                starts = STARTS[start]
            else:
                # One 503. Use the corresponding five lines from the first
                # successful take, recorded with the same model and voice.
                source = original
                starts = [first_take[i]['start'] - trim for i in range(start, start + 5)]
                begin = starts[0] - .1
                end = first_take[start + 5]['start'] - trim - .13
            if not begin < starts[0] <= starts[-1] < end:
                raise ValueError(f'Invalid narration timings at line {start}')
            cues.extend(count / RATE + t - begin for t in starts)
            segment = source[2 * round(begin * RATE):2 * round(end * RATE)]
            destination.writeframes(segment)
            count += len(segment) // 2
        # A short closing hold keeps the final sentence on screen.
        destination.writeframes(b'\0' * RATE * 2)
        count += RATE
    return cues, count / RATE


def timestamp(seconds):
    ms = max(0, round(seconds * 1000))
    return f'{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d}.{ms % 1000:03d}'


def captions(out, texts, cues, duration):
    rows = ['WEBVTT', '']
    for i, (text, start, end) in enumerate(zip(texts, cues, cues[1:] + [duration]), 1):
        rows.extend([str(i), f'{timestamp(start)} --> {timestamp(end - .04)}', text, ''])
    out.write_text('\n'.join(rows), encoding='utf-8')


def shot_positions(shots, root):
    import numpy as np
    from PIL import Image

    # Find the frame corresponding to the completed browser interaction. Keep
    # a short recording leading into it, then hold the sharp original screenshot.
    movies, timings = {}, {}
    for _, name, clip in shots:
        if not clip:
            continue
        if clip not in movies:
            pixels = ffmpeg('-i', root / f'{clip}.webm', '-vf', 'fps=8,scale=160:90,format=gray',
                            '-pix_fmt', 'gray', '-f', 'rawvideo', 'pipe:1', capture=True)
            movies[clip] = np.frombuffer(pixels, dtype=np.uint8).reshape(-1, 90, 160).astype(np.int16)
        with Image.open(root / f'{name}.jpg') as image:
            sample = np.asarray(image.convert('L').resize((160, 90)), dtype=np.int16)
        differences = np.abs(movies[clip] - sample).mean(axis=(1, 2))
        best = int(np.argmin(differences))
        # Ignore captures whose source does not match the selected key frame.
        if differences[best] < 9 and best >= 8:
            near = np.flatnonzero(differences <= differences[best] + .32)
            timings[name] = float(near[0]) / 8
    return timings


def encode_shot(task, root, scratch, timings):
    number, first, last, name, clip = task
    target = scratch / f'{number:03}.mp4'
    frames = last - first
    duration = frames / FPS
    image = root / f'{name}.jpg'
    initial = max(0, timings.get(name, 0) - .92)
    movement = min(1.12, duration * .52, timings.get(name, 0) + .17)
    if clip and movement > .65:
        inputs = ['-ss', initial, '-t', movement, '-i', root / f'{clip}.webm',
                  '-loop', '1', '-framerate', FPS, '-t', duration - movement + .08, '-i', image]
        filters = ['-filter_complex',
                   '[0:v]fps=30,format=yuv420p,setsar=1[a];[1:v]fps=30,format=yuv420p,setsar=1[b];[a][b]concat=n=2:v=1:a=0[v]',
                   '-map', '[v]']
    else:
        inputs = ['-loop', '1', '-framerate', FPS, '-i', image]
        filters = ['-vf', 'format=yuv420p,setsar=1']
    ffmpeg(*inputs, *filters, '-frames:v', frames, '-an', '-c:v', 'libx264', '-threads', '2',
           '-preset', 'veryfast', '-crf', '21', '-profile:v', 'high', '-pix_fmt', 'yuv420p', target)
    print(f'{name}: {duration:.2f}s, motion {clip if clip and movement > .65 else "none"}', flush=True)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--narration-dir', type=Path,
                        help='Use narration.wav, cues.json and script.json in this directory')
    args = parser.parse_args()
    root = args.capture.resolve()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    narration_dir = args.narration_dir.resolve() if args.narration_dir else root
    texts = [line for scene in json.loads((narration_dir / 'script.json').read_text()) for line in scene['lines']]
    vtt = out / 'researchtrace-demo-zh.vtt'
    with tempfile.TemporaryDirectory(prefix='rt-demo-render-') as work:
        scratch = Path(work)
        if args.narration_dir:
            audio = narration_dir / 'narration.wav'
            duration = len(read_frames(audio)) / (2 * RATE)
            cues = json.loads((narration_dir / 'cues.json').read_text())
        else:
            audio = scratch / 'voice.wav'
            cues, duration = assemble_voice(root, audio)
        assert len(cues) == len(texts) == 51
        assert 0 <= cues[0] and all(a < b for a, b in pairwise(cues)) and cues[-1] < duration
        assert 300 <= duration <= 480, f'Narration duration {duration:.2f}s outside competition range'
        captions(vtt, texts, cues, duration)
        shots = []
        for index, images in SHOTS.items():
            start = cues[index] if index else 0
            delta = (cues[index + 1] if index + 1 < len(cues) else duration) - start
            shots.extend((round((start + shift * delta) * FPS), name, clip) for shift, name, clip in images)
        endpoints = [row[0] for row in shots[1:]] + [round(duration * FPS)]
        tasks = [(i, first, last, name, clip) for i, ((first, name, clip), last) in enumerate(zip(shots, endpoints))]
        timings = shot_positions(shots, root)
        with ThreadPoolExecutor(max_workers=3) as pool:
            files = list(pool.map(lambda task: encode_shot(task, root, scratch, timings), tasks))
        listing = scratch / 'concat.txt'
        listing.write_text(''.join(f"file '{path.name}'\n" for path in files))
        video = out / 'researchtrace-demo-1080p.mp4'
        ffmpeg('-f', 'concat', '-safe', 1, '-i', listing, '-i', audio, '-i', vtt,
               '-map', '0:v:0', '-map', '1:a:0', '-map', '2:s:0', '-c:v', 'copy',
               '-af', 'loudnorm=I=-16:LRA=7:TP=-1.5', '-ar', 48000, '-c:a', 'aac', '-b:a', '128k',
               '-c:s', 'mov_text', '-metadata:s:s:0', 'language=zho', '-disposition:s:0', '0',
               '-metadata', 'title=ResearchTrace 研证 · 参赛演示',
               '-movflags', '+faststart', video)
    (out / 'timeline.json').write_text(json.dumps({'duration_seconds': duration, 'subtitles': len(texts),
                                                 'shots': len(shots), 'sources': sorted({s for _, s, _ in shots})},
                                                ensure_ascii=False, indent=2) + '\n')
    print(f'{video}: {duration:.2f}s, {len(texts)} captions', flush=True)


if __name__ == '__main__':
    main()
