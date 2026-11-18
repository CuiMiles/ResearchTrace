"""Style a ResearchTrace VTT and burn matching captions into the download MP4."""
import argparse
import os
import re
import tempfile
import unicodedata
from pathlib import Path

from assemble_demo import ffmpeg

BLUE = '#8dd5ff'
NAVY = '#0d1728'
VTT_STYLE = f'''STYLE
::cue {{
  color: {BLUE};
  background-color: {NAVY};
  font-weight: 600;
}}'''

TIMING = re.compile(r'^(\d\d:\d\d:\d\d\.\d{3}) --> (\d\d:\d\d:\d\d\.\d{3}).*$')
ASS_HEADER = '''[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Demo,Source Han Sans SC,43,{blue},{blue},{navy},{navy},-1,0,0,0,100,100,0,0,3,7,0,2,126,126,120,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''


def ass_color(rgb):
    return f'&H00{rgb[5:7]}{rgb[3:5]}{rgb[1:3]}'


def web_cue(caption):
    # Break long CJK cues explicitly so native Windows captions fit the video.
    if '\n' in caption:
        return '68%', caption
    tokens = re.findall(r'[A-Za-z0-9]+(?:[.+_/-][A-Za-z0-9]+)*|.', caption)
    widths = [sum(2 if unicodedata.east_asian_width(char) in 'WF' else 1 for char in token)
              for token in tokens]
    total = sum(widths)
    if total <= 56:
        return '72%', caption
    columns = 0
    candidates = []
    for index, width in enumerate(widths[:-1], 1):
        columns += width
        if columns <= 56 and total - columns <= 56 and tokens[index][0] not in '，。；、？！：）':
            natural_break = tokens[index - 1][-1] in '。！？，；、： '
            score = abs(2 * columns - total) - (8 if natural_break else 0)
            candidates.append((score, index))
    if not candidates:
        return '72%', caption
    _, split = min(candidates)
    return '68%', ''.join(tokens[:split]).rstrip() + '\n' + ''.join(tokens[split:]).lstrip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('vtt', type=Path)
    parser.add_argument('clean_mp4', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    vtt = ['WEBVTT', VTT_STYLE]
    ass = [ASS_HEADER.format(blue=ass_color(BLUE), navy=ass_color(NAVY))]
    for block in args.vtt.read_text(encoding='utf-8-sig').strip().split('\n\n')[1:]:
        if block.startswith('STYLE\n'):
            continue
        number, timing, caption = block.split('\n', 2)
        match = TIMING.fullmatch(timing)
        if not match or not number.isdigit() or not caption.strip():
            raise ValueError(f'Invalid subtitle cue {number}')
        start, end = match.groups()
        line, wrapped = web_cue(caption)
        vtt.append(f'{number}\n{start} --> {end} line:{line},end size:92%\n{wrapped}')
        escaped = caption.replace('{', r'\{').replace('}', r'\}').replace('\n', r'\N')
        ass.append(f'Dialogue: 0,{start[:-1]},{end[:-1]},Demo,,0,0,0,,{escaped}')

    if len(vtt) == 2:
        raise ValueError('No subtitle cues found')
    with tempfile.TemporaryDirectory(prefix='rt-demo-captions-') as work:
        scratch = Path(work)
        (scratch / 'captions.ass').write_text('\n'.join(ass) + '\n', encoding='utf-8')
        draft = output / 'researchtrace-demo-academic-blue-draft.mp4'
        ffmpeg('-i', args.clean_mp4, '-map', '0:v:0', '-map', '0:a:0',
               '-vf', f'ass={scratch}/captions.ass', '-c:v', 'libx264', '-profile:v', 'baseline',
               '-level:v', '4.0', '-pix_fmt', 'yuv420p', '-color_range', 'tv', '-preset', 'veryfast',
               '-threads', '6', '-crf', '20', '-maxrate', '1800k', '-bufsize', '3600k', '-g', '60',
               '-c:a', 'copy', '-movflags', '+faststart', draft)
        os.replace(draft, output / 'researchtrace-demo-academic-blue-1080p.mp4')
    (output / 'researchtrace-demo-academic-blue-zh.vtt').write_text(
        '\n\n'.join(vtt) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
