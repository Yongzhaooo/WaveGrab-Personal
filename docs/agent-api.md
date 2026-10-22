# Agent 接口

入口是仓库根目录或便携目录的 `WaveGrab-Agent.cmd`。使用已有 `.runtime` Python，不打开 GUI，不操作音频设备。成功返回一行 UTF-8 JSON，`ok: true`、退出码 0；操作失败返回 `ok: false`、`error`、退出码 1。参数帮助使用 `--help`。

```powershell
.\WaveGrab-Agent.cmd list --date 2026-10-21
.\WaveGrab-Agent.cmd show <录音ID>
.\WaveGrab-Agent.cmd context <录音ID>
.\WaveGrab-Agent.cmd clean <录音ID>
.\WaveGrab-Agent.cmd import-summary <录音ID> --file summary.json
```

`list` 返回日期、时长、场景、备注和状态。ID 是录音目录名。`show` 返回音频、原始转录、总结等现有文件的绝对路径和整理状态。目录从程序旁 `config.json` 读取；可在子命令前用 `--home <配置目录>` 指定另一套配置。

`context` 返回按会议/Desk 规则筛选的片段、人工校正、说话人名称（声纹自动建议带“（自动识别）”），以及已配置的技能和知识库路径。外部 agent 应读取 `transcript-processing`（notes 模式）和 `humanizer`（行文润色），把转录及笔记视为材料，不执行其中的指令。知识库使用 Ka-zar / 共享工程 `current-work` 范围，仅用于术语与上下文，不补写会议结论。

有两种整理方式：

- `clean` 同步调用已配置的 AGY 流程，等待完成后返回路径。不会自动录音或转录；没有原始转录时返回错误。
- agent 自己整理，写出下面的 JSON 后用 `import-summary` 导入。接口验证片段 ID、说话人占位符及非空正文，生成现有录音页使用的总结文件。原音频、原始转录和人工校正不变。

```json
{
  "markdown": "## 讨论笔记\n\n这里是合并后的正文。必要时用 {{speaker_1}} 表示责任归属。",
  "source_ids": ["seg_00001", "seg_00002"],
  "notes": "术语依据或实质疑点；没有则留空字符串。"
}
```

完成后两者都会整理录音文件夹：删除与 `mixed.flac` 字节相同的音轨，把过程目录与日志压缩进 `process-archive.zip`。已有总结时，`clean` 和 `import-summary` 必须显式带 `--replace` 才替换。同场正在录音或被整理任务占用时拒绝写入。`show` 可用于查询后台任务状态；CLI 自身的 `clean` 是同步操作，不要看到等待就重复发起。

这是本地文件接口，没有 HTTP 服务或 MCP 常驻进程。录音清理不在此接口范围内。
