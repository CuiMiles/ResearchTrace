# 技术文档（赛题 2.3）LaTeX 源码

输出：`deliverables/ResearchTrace_技术文档.pdf`（当前 27 页，赛题上限 30 页）。

## 编译

```bash
./build.sh        # latexmk -xelatex，产物复制到 deliverables/
```

依赖（Ubuntu 24.04）：

```bash
sudo apt install texlive-xetex texlive-lang-chinese texlive-latex-extra texlive-pictures \
  texlive-fonts-recommended texlive-fonts-extra texlive-science latexmk fonts-noto-cjk fonts-inter
```

字体为 Inter + Noto Sans CJK SC；换字体只改 `rtstyle.sty` 的“字体”一节。Overleaf 上选择 XeLaTeX 编译器并上传所需字体即可。

## 目录

| 路径 | 内容 |
|---|---|
| `main.tex` | 入口；封面信息（团队、成员、演示地址、日期）在文件开头的宏里改 |
| `rtstyle.sty` | 版式、配色、TikZ / pgfplots 样式、截图框与提示框 |
| `chapters/` | 封面与目录、8 个章节，图表以 TikZ 源码内嵌在对应章节 |
| `figures/` | 界面截图（`\shot{figures/xxx.png}`；文件缺失时自动显示占位框） |
| `data/` | 图表数据，由脚本从 `evidence/` 的真实评测记录生成 |
| `tools/make_figdata.py` | 重新生成 `data/`：`python3 docs/tech-report/tools/make_figdata.py` |

## 修改提示

- 文中数字均来自仓库 `evidence/` 与测试日志；检索评测的曲线、热力图由 `tools/make_figdata.py` 计算，更新评测后重跑脚本再编译。
- TikZ 对齐节点里换行（`\\`）不能落在花括号分组内，多行小字用 `\sublines{第一行\\第二行}`。
- 带标题和说明的模块框用 `\rtnode[样式]{名字}{坐标}{文本宽}{标题}{小字}`，样式有 `box / boxB / boxT / boxA / boxV / boxR / boxN`。
- `figures/` 中除 `ui-evidence.png`（来自 `docs/images/`，真实模型问答后的原文定位）外，均为本地无密钥环境对赛题资料包 20 篇论文的实拍，拍摄时隐藏了“模型未配置”提示条。录制正式视频或需要问答页面截图时，建议用公网环境重拍替换。
