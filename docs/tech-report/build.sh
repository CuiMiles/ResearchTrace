#!/usr/bin/env bash
# 编译技术文档并复制到 deliverables/。依赖：TeX Live (xelatex, ctex, tikz, pgfplots, tcolorbox, fontawesome5)、
# 字体 Inter 与 Noto Sans CJK SC（Ubuntu: apt install texlive-xetex texlive-lang-chinese texlive-latex-extra
# texlive-pictures texlive-fonts-recommended texlive-fonts-extra latexmk fonts-noto-cjk fonts-inter）。
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p build
latexmk -xelatex -interaction=nonstopmode -halt-on-error -outdir=build main.tex
mkdir -p ../../deliverables
cp build/main.pdf "../../deliverables/ResearchTrace_技术文档.pdf"
pages=$(pdfinfo build/main.pdf | awk '/^Pages/{print $2}')
echo "OK: deliverables/ResearchTrace_技术文档.pdf （${pages} 页，赛题上限 30 页）"
