# SSE 接入教程

本文演示如何独立运行 Kid English MCP 服务，并通过 Server-Sent Events (SSE) 与之通信。流程包括：

1. 安装依赖、启动 SSE HTTP 服务；
2. 通过 `/sse` 订阅事件流，使用 `/messages` 发送 JSON-RPC MCP 请求；
3. 观察返回的数据并正确关闭连接；
4. 运行自动化测试（`pytest -k sse`）确认链路稳定。

## 1. 安装依赖

建议使用虚拟环境，安装项目及测试依赖。FAISS 可选，项目自带 NumPy 余弦回退。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[test]
```

## 2. 启动 SSE 服务

执行 CLI 命令即可启动教学核心、SQLite 存储和 SSE HTTP 服务。下面示例绑定端口 8765，默认读取项目中的课程与参考词表。

```bash
kid-english-mcp --host 0.0.0.0 --port 8765
```

终端会输出：

```
Serving KidEnglish MCP SSE server on http://0.0.0.0:8765
```

保持该进程运行，接下来在另一个终端进行客户端测试。

## 3. 订阅事件并调用工具

在第二个终端中订阅 SSE 流，可自定义 `stream` 参数，只要与 JSON-RPC 请求体中的 `stream` 保持一致即可。

```bash
curl -N http://127.0.0.1:8765/sse?stream=demo-stream
```

`-N` 参数会让 curl 持续输出心跳注释，直到收到事件数据。

随后调用 MCP 工具。HTTP 版 MCP 采用 JSON-RPC 2.0 协议，下面示例通过 `tools.call` 调用 `start_session`，为 5-6 岁的孩子开启问候主题的学习会话：

```bash
curl -X POST http://127.0.0.1:8765/messages \
  -H 'Content-Type: application/json' \
  -d '{
        "jsonrpc": "2.0",
        "id": "demo-1",
        "method": "tools.call",
        "params": {
          "name": "start_session",
          "arguments": {
            "user_id": "kid-demo",
            "age_band": "5-6",
            "goal": "greetings",
            "locale": "zh-CN"
          },
          "stream": "demo-stream"
        }
      }'
```

SSE 终端会收到：

```
event: message
data: {"jsonrpc": "2.0", "id": "demo-1", "result": {"session_id": "...", "next_activity": {...}}, "done": true}
```

使用返回的 `session_id` 继续提交口语文本或请求下一个活动：

```bash
curl -X POST http://127.0.0.1:8765/messages \
  -H 'Content-Type: application/json' \
  -d '{
        "jsonrpc": "2.0",
        "id": "demo-2",
        "method": "tools.call",
        "params": {
          "name": "submit_utterance",
          "arguments": {
            "session_id": "<上一步返回的 SESSION>",
            "utterance_text": "hello"
          },
          "stream": "demo-stream"
        }
      }'
```

每次调用都会在同一条 `/sse` 连接中推送新的事件。完成后按 `Ctrl+C` 结束 SSE 订阅。

### 同步模式

如果在 JSON-RPC 请求的 `params` 中省略 `stream`/`stream_id` 字段，服务器会直接以 JSON 形式同步返回结果。

### 工具发现

可先访问 `GET /.well-known/mcp.json` 或调用 `tools.list` 获取完整工具描述：

```bash
curl -X POST http://127.0.0.1:8765/messages \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":"meta","method":"tools.list"}'
```

## 4. 自动化测试

项目自带的回归测试会临时启动 SSE 服务、订阅 `/sse`，并断言返回结构是否正确。可单独运行：

```bash
pytest -k sse
```

当测试通过时，说明 SSE 管道和工具调用均运作正常。

## 5. 可选分级词汇

在 `references/<年龄段>/<目标>/words.txt` 中放置自定义词汇表（每行一个词，`#` 为注释）。如果存在匹配文件，服务会在返回的活动中附带 `lexicon_words` 字段，便于 UI 展示卡片或图片提示。

目录示例：

```
references/
└── 5-6/
    └── greetings/
        └── words.txt
```

修改词表后重新启动 SSE 服务即可生效。
