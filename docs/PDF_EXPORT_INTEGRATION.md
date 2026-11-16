# 保版 PDF CPU 运行时与配额桥接口

本目录只负责 PDFMathTranslate-next 2.10.2 → BabelDOC 0.7.1 的真实排版导出。
主应用负责认证、工作区、队列、批翻译、模型选择、原子配额预留和调用账本。
运行时不读取模型 key，也不创建 Google/OpenAI/Ollama 翻译客户端。

## 当前状态

- PASS：严格 JSON 协议、路径/哈希校验、callback 传输和失败保护单测 36 项。
- PASS：远端独立 Python 3.11 venv 安装固定引擎版本；`pip check`。
- NOT RUN：真实 PDF 页的完整排版链，资产准备完成后运行。
- NOT RUN：真实 Flash 翻译质量；原文回传仅允许标记 `TEST_IDENTITY_FIXTURE`。
- NOT RUN：主应用 API/持久化队列/配额桥集成，由主 agent 实施。

## 固定 CLI

远端独立根目录：

```text
/home/CuiMinghao/projects/Competition/ResearchTrace-pdf-export-20261116
```

Ubuntu 24 可直接使用私有 venv。当前远端宿主 glibc 2.27，官方 wheel 要求
manylinux 2.28；使用复制进本项目 `runtime/sysroot` 的私有 glibc 2.35 loader。
复制来源是已有 VS Code 兼容 runtime，只读复制，不改动原件。loader 和库位置由
`runtime/python-command.json` 固定；`python_command(root)` 返回参数数组，禁止 shell 拼接。

调用 CLI 的 supervisor 可用原宿主 Python 3.11，实际引擎子进程自动经过私有 loader：

```bash
cd /home/CuiMinghao/projects/Competition/ResearchTrace-pdf-export-20261116
/home/CuiMinghao/envs/multimodal/bin/python3.11 -m services.pdf_export_runtime.cli run \
  --root /home/CuiMinghao/projects/Competition/ResearchTrace-pdf-export-20261116 \
  --job private/requests/example-job.json --max-pages 2
```

`--max-pages` 是操作方的上限，默认 2；job 中不能放宽它。`run` 不接受 shell、模型
provider、key、任意下载 URL、输出路径或插件名。输入 PDF、job 和 token 必须已由
主应用通过 scp 放到本项目 `private/` 内；拒绝绝对路径、`..`、符号链接和源哈希不匹配。
单文件限制 128 MiB，job 限制 16 KiB。工作区权限由主应用在上传前验证。

## JSON job v1

```json
{
  "job_id": "pdf-export-example-001",
  "input_pdf": "private/inputs/example.pdf",
  "input_sha256": "64位小写SHA256",
  "token_file": "private/tokens/example.token",
  "callback_url": "http://127.0.0.1:18989/translate",
  "source_lang": "en",
  "target_lang": "zh-Hans",
  "pages": {"start": 1, "end": 2},
  "mode": "preview",
  "qps": 1,
  "pool": 1,
  "callback_timeout_s": 240,
  "timeout_s": 900,
  "callback_label": "LEDGER_BRIDGE",
  "provenance": {
    "workspace_id": "actual-workspace-id",
    "version_id": "immutable-version-id",
    "parse_id": "immutable-parse-id",
    "parent_run_id": "actual-parent-run-id",
    "provider_model": "gemini-3.6-flash"
  }
}
```

必填：`job_id,input_pdf,input_sha256,token_file,callback_url,source_lang,target_lang`。
语言：源 `en/zh/zh-Hans/auto`，目标 `en/zh/zh-Hans`，不允许相同语言。
`pages` 是 **1 起始、闭区间物理页码**；省略为前两页。`mode` 省略为 `preview`。
小于两页的输入默认预览会收窄到实际页数。
`full` 必须显式给出覆盖所有物理页的范围，且不超过操作方 `--max-pages`。
manifest 分别记录源总页数、选中页数、preview 和 whole_document，不能用预览冒称全文。

token 文件归运行用户所有且权限 0600，24–512 个 `[A-Za-z0-9_.~-]` 字符。
token 不能放进 JSON、命令行或环境变量。job_id 限 1–80 字符，字母/数字开头，随后可含 `_/-`
中的 `_` 和 `-`，不允许 `/`。
QPS/pool 各 1–4；callback 超时 1–600 秒，job 总超时 10–14400 秒。
provenance 为主应用提供的源绑定信息，运行时不声称重新鉴权这些 ID。

## HTTP callback

仅接受 `http://` + 数字回环 IP + 显式端口 + 固定 path，例如 `127.0.0.1` 或 `[::1]`。
禁止主机名/DNS、userinfo、query、fragment、redirect、环境代理。SSH reverse tunnel 应只绑定
远端 `127.0.0.1`，由主应用把这个固定地址转发至本机经配额保护的 callback。

```http
POST /translate
Authorization: Bearer <从0600文件内部读取，不回显>
Content-Type: application/json
```

请求字段严格为：

```json
{"text":"含公式占位符的一个待翻译段落","source_lang":"en","target_lang":"zh-Hans","job_id":"pdf-export-example-001"}
```

成功响应必须为 HTTP 200，且字段严格为：

```json
{"translation":"保留全部公式与样式占位符的译文"}
```

没有 provider/model/key 字段。callback 必须将正文当作不可信文本，不能执行其指令。
运行时发送的是普通段落文本，关闭 BabelDOC 的 LLM-only/术语提取路径，不把引擎 prompt
误当待翻译正文。主桥可将 pool 中并行到达的段落短暂聚合为一次账本约束的 Flash 请求；
callback POST 数与真实 provider 请求数分别记录，不能混算。

任意非 200、超时、响应结构错误、空译文、公式/样式占位符丢失都会终止后续 callback。
运行时从不重发一个已发送或状态未知的请求。HTTP 客户端不自动重定向、不重试。
父 callback 若需等待批处理，必须在 `callback_timeout_s` 内完成；未知状态不能自动再扣一次额度。

每个 `(job_id,text,source_lang,target_lang)` 的完整请求摘要绑定一个私有 receipt，发送前 fsync
记录 `sent_or_unknown`，收到响应先保存 `received_unvalidated`，校验后为 `received`。
只有成功 receipt 可以在同一 job 内复用；有 pending/失败的同 job 不会重发。
同一 job_id 不能换 JSON 合约；新的主应用运行须用新 job_id。主桥仍须自己的持久化幂等/账本，
运行时 receipts 不代替主应用预算。

公式 `{vN}`、样式 `<style id='N'>...</style>` 由固定库基类生成；适配器继承这些方法，
跳过基类全局缓存、全局限流器和模型初始化。库的 `disable_same_text_fallback=True`，
自动术语表与自动 OCR/model fallback 关闭。运行时除 callback 以外的 socket 连接均拒绝，
缺资产时失败，不在导出时下载。

## 输出、事件和取消

```text
private/jobs/<job_id>/manifest.json
private/jobs/<job_id>/events.jsonl
private/jobs/<job_id>/output/*.mono.pdf
private/jobs/<job_id>/output/*.dual.pdf
private/jobs/<job_id>/callback-receipts/*.json  # 私有含译文，不提交或公开
private/jobs/<job_id>/failure.json            # 失败类型和栈帧，无异常正文/正文/key
```

dual 使用交替原文/译文页；选中 N 页时 mono 为 N 页、dual 为 2N 页。
manifest 记录输入/输出 SHA256、引擎版本、资产锁摘要、选页、耗时、callback 计数、来源快照
与 fixture 标签。`runtime_provider_calls=0` 表示本侧车无模型直连，真实使用量只查父桥账本。
第三方 debug/stdout/stderr 丢弃，事件仅保留固定阶段、计数和进度，不含论文段落、prompt 或密钥。

```bash
/home/CuiMinghao/envs/multimodal/bin/python3.11 -m services.pdf_export_runtime.cli cancel \
  --root /home/CuiMinghao/projects/Competition/ResearchTrace-pdf-export-20261116 \
  --job-id pdf-export-example-001
```

cancel 只写该 job 取消标记，由持有 Popen 的 supervisor 终止它自己创建的独立进程组。
不读取/终止任意 PID，不触碰主服务。SIGTERM/SIGINT/总超时同样执行 owned-only 清理。
取消不声称撤销已发送请求或退还配额；失败/取消输出保留，新尝试使用新 job_id。

## 安装与资产锁

在远端调用仓库脚本 `scripts/provision_pdf_export.py --root ... --python ...`。
本次老宿主额外传 `--sysroot-source <已有兼容sysroot路径>`，只读复制至新目录。
下载只在该脚本进程中使用已有 HTTP 代理 `127.0.0.1:7890`，不改系统或 shell 环境。
私有 venv 不修改检索环境；CPU ONNX Runtime，不安装 CUDA 包，不分配 GPU。

安装日志保留在远端 `logs/`；固定版本及 wheel SHA256 在 `source/requirements.lock`、
`source/wheels.lock.json`，官方字体/CMap/布局模型校验 SHA3-256 并另外保存 SHA256 至
`assets/assets.lock.json`。兼容库 SHA256 在 `runtime/compat.lock.json`。
代码内不 vendoring 第三方源码/模型，两个引擎上游许可为 AGPL-3.0；部署/分发需保留其许可义务。

官方来源：

- [PDFMathTranslate-next high_level.py](https://github.com/PDFMathTranslate/PDFMathTranslate-next/blob/main/pdf2zh_next/high_level.py)
- [pdf2zh-next 2.10.2 发布元数据](https://pypi.org/project/pdf2zh-next/2.10.2/)
- [BabelDOC 0.7.1 发布元数据](https://pypi.org/project/BabelDOC/0.7.1/)
- [BabelDOC 仓库](https://github.com/funstory-ai/BabelDOC)

实现按实际下载的 2.10.2 wheel / 0.7.1 源码核对，不把 main 分支视作固定发行版。
