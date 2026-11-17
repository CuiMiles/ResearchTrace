import { Fragment, useMemo } from 'react';
import katex from 'katex';
import 'katex/dist/katex.min.css';

/**
 * Parsed text with LaTeX math rendered by KaTeX. OCR and layout engines emit
 * formulas as `$…$` / `$$…$$`; printed raw they read like `$\sqrt { d _ { k } }$`.
 * KaTeX runs with `trust: false`, so text from an untrusted PDF cannot add links,
 * classes or HTML. Inline math must look like math (a LaTeX command, sub/superscript,
 * braces, or a single symbol) so prices such as "$5 and $10" stay text.
 */
const MATH = /\$\$([\s\S]{1,2000}?)\$\$|\$(?!\s)([^$\n]{1,300}?)(?<!\s)\$/g;
const LOOKS_LIKE_MATH = /[\\_^{}]|^[A-Za-zͰ-Ͽ]$/;
// Markdown escapes left by OCR (e.g. "Vaswani\*") outside math.
const unescape = (text: string) => text.replace(/\\([*_#[\]`~])/g, '$1');

type Piece = { text: string } | { tex: string; display: boolean };

export function splitMath(text: string): Piece[] {
  const pieces: Piece[] = [];
  let last = 0;
  for (const match of text.matchAll(MATH)) {
    const display = match[1] !== undefined;
    const tex = (display ? match[1] : match[2]).trim();
    if (!tex || (!display && !LOOKS_LIKE_MATH.test(tex))) continue;
    if (match.index! > last) pieces.push({ text: unescape(text.slice(last, match.index)) });
    pieces.push({ tex, display });
    last = match.index! + match[0].length;
  }
  if (last < text.length) pieces.push({ text: unescape(text.slice(last)) });
  return pieces;
}

function render(tex: string, display: boolean) {
  try {
    return katex.renderToString(tex, { displayMode: display, throwOnError: true, trust: false, strict: 'ignore', output: 'html' });
  } catch {
    return null; // not valid TeX: show the source text instead of a red error
  }
}

export function MathText({ text }: { text: string }) {
  const pieces = useMemo(() => splitMath(text), [text]);
  return <>{pieces.map((piece, i) => {
    if ('text' in piece) return <Fragment key={i}>{piece.text}</Fragment>;
    const html = render(piece.tex, piece.display);
    if (html === null) return <Fragment key={i}>{piece.display ? `$$${piece.tex}$$` : `$${piece.tex}$`}</Fragment>;
    return <span key={i} className={piece.display ? 'math-display' : 'math-inline'} dangerouslySetInnerHTML={{ __html: html }} />;
  })}</>;
}
