# 自动清洗

转录完成后，WaveGrab 启动独立后台清洗进程。录音记录页的“清洗 / 重试”可处理已有转录；“音频位置”和“清洗稿位置”在资源管理器中选中文件，不播放声音。

在便携程序旁创建 `cleanup-config.json`（本机配置，不提交 Git）：

```json
{
  "enabled": true,
  "python": "<本机 Python 可执行文件>",
  "agy": "<已登录的 AGY CLI 可执行文件>",
  "model": "gemini-3.8-flash-medium",
  "knowledge_root": "<Ka-zar / 共享工程知识库根目录>",
  "knowledge_python": "<知识库 Python 可执行文件>"
}
```

所有路径填写实际绝对路径。模型需出现在 `agy models` 中。清洗脚本仅用 Python 标准库及同目录的 `transcript_store.py`；知识库 Python 沿用知识库自己的环境。设置 `enabled: false` 停用清洗。缺少配置或登录失败会显示失败状态，不影响录音或原始转录。

使用现有 AGY CLI 的 `stream-json` 输入、结构化输出和默认权限，不自动批准工具，不改变账户或模型。文字与相关检索摘录会发送给 AGY；音频不发送。检索固定 `current-work`（Ka-zar / 共享工程），`exact_fts`，公司敏感资料 profile，保留来源和检索警告。检索失败则停止，零命中如实保留，不换语料库兜底。

每场保存：

- `transcript.raw.json` / `transcript.raw.md`：原始识别，保持不变。
- `transcript.agy.json`：AI 清洗文字、疑点和本次依据位置。
- `transcript.edits.json`：人工校正，优先于 AI；改名继续使用 `speakers.json`。
- `exports/transcript.clean.md`：按当前场景、名称与人工校正生成的清洗草稿。
- `exports/cleanup-notes.md`：术语依据与不确定项。
- `cleanup.status.json` / `cleanup.log` / `cleanup-runs/`：运行状态、故障与逐批输入、检索、响应证据。

关闭界面不取消清洗；睡眠/退出系统可能中断任务，可从记录页重试。OS 文件锁避免同一场重复处理。失败不替换已有 AI 文字；原稿始终保留。切换主要说话人或修改人工文字后可重新清洗；运行中发生这些变化，本次结果留在依据目录，提示重试。每批逐段校验 ID 和非空文字，不把结构通过等同于事实准确，草稿仍需核对。
