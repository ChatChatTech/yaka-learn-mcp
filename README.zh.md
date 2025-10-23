# 英语少儿口语 MCP 服务器

该项目提供一个纯文本的 Model Context Protocol (MCP) 服务器，帮助 3-10 岁的中国孩子练习英语口语。服务内置 SQLite 存储、循环教学策略、激励机制，以及可选的词汇参考表。你可以直接运行内置的 SSE 服务（`/sse` 端点），或将核心类嵌入到自己的工作流（例如 n8n）中。

## 系统梳理

1. **教学核心**：`server.py` 中的 `KidEnglishMCPServer` 负责管理会话、发放 XP/贴纸、挑选教学卡片，并结合 `srs.py` 实现简化的间隔复习。
2. **数据与扩展**：`db.py` 使用 SQLite 持久化学习进度，`vectorstore.py`/`references.py` 则提供可选的向量检索和分级词汇扩展能力。
3. **SSE 对外服务**：`sse_server.py` 按 MCP 规范暴露 `/sse`、`/messages` 与 `/.well-known/mcp.json`，方便 MCP 兼容客户端或 n8n 直接通过事件流消费结果。

更多使用细节见 [docs/SSE教程.md](docs/SSE教程.md)，内含 curl 示例与自动化测试说明。

## 功能亮点

- **杜林戈风格的教学循环**：短句提示 + 纠错反馈 + XP 与贴纸奖励。
- **按学龄调节的提示**：幼龄段 ≤8 个词，高龄段 ≤12 个词，并在需要时提供中文支架。
- **轻量级间隔复习**：SM-2 简化算法混排新卡与复习卡。
- **完全独立运行**：纯 Python + SQLite，可选 FAISS 检索，无需第三方中间件。
- **内置 SSE 网关**：`kid-english-mcp` 命令即可启动符合 MCP 客户端习惯的事件流接口。
- **可选词汇参考**：`references/<年龄段>/<目标>/words.txt` 支持自定义重点词汇。

## 快速开始

1. **安装依赖**

   ```bash
   pip install -e .[test]
   ```

2. **启动 SSE 服务**

   ```bash
   kid-english-mcp --host 0.0.0.0 --port 8765
   ```

   可用接口：

   - `GET /.well-known/mcp.json`：返回工具清单与端点描述。
   - `GET /sse?stream=<id>`：订阅 SSE 事件流；若省略 `stream` 参数，服务器会生成一个随机 ID。
   - `POST /messages`：发送 JSON-RPC 2.0 请求，例如 `{"jsonrpc":"2.0","method":"tools.list"}` 或 `{"jsonrpc":"2.0","method":"tools.call","params":{"name":"start_session","arguments":{...},"stream":"同一个 id"}}`。
   - `GET /healthz`：健康检查。

   若 `tools.call` 的 `params` 中未包含 `stream`/`stream_id` 字段，会以同步 JSON 形式直接返回；如果提供了 `stream`，HTTP 响应将返回 `202 Accepted`，真正的结果或错误会通过同一个 SSE 连接推送。

3. **在代码中调用**

   ```python
   from english_kids_mcp import KidEnglishMCPServer

   server = KidEnglishMCPServer()
   session = server.start_session("kid_001", "5-6", "greetings", "zh-CN")
   feedback = server.submit_utterance(session["session_id"], "hello")
   ```

4. **接入 n8n**

   - Webhook 接收 ASR 文本；
   - HTTP 节点调用 `/messages`（`tools.call`），或直接调用 `KidEnglishMCPServer`；
   - 将 `feedback_text` 发往 TTS，`next_activity.prompt_text` 用于 UI 提示。

## 词汇参考目录

在项目根目录的 `references/` 下，可按照学龄段与学习目标创建二级目录：

```
references/
└── 5-6/
    └── greetings/
        └── words.txt
```

`words.txt` 每行一个词汇，允许添加注释行（以 `#` 开头）。若存在匹配文件，服务会将词汇列表放入 `Activity.lexicon_words` 字段，便于外部应用展示图片、卡片或额外提示。

## 测试

```bash
pytest
```

默认测试会验证核心教学循环以及 SSE 客户端往返流程；你也可以运行 `pytest -k sse` 单独检查 `/sse` 接口。

## 后续扩展建议

- 通过函数调用接入更强的 LLM 评测，获得更细粒度的纠错建议。
- 扩充 `curriculum.json`，加入情景会话、自然拼读、挑战任务等内容。
- 在 `references/` 中维护分层词表或常见句型，结合 UI 做逐步解锁。
- 利用 `get_progress` 和 `save_note_for_parent` 构建家长侧的中文学习报告。

## 许可证

MIT License
