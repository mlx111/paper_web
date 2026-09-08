# mypaperweb MCP 使用说明

本文档用于本地测试和面试演示 `mypaperweb` 的 MCP 工具能力。当前 MCP V1.1 覆盖三个只读工具：知识库检索、Web Search、当前时间查询，并已接入 Run Trace。

## 当前能力

- MCP Server：`app/mcp_server.py`
- MCP 适配层：`app/mcp_tools.py`
- Server 名称：`mypaperweb-tools`
- Transport：本地 stdio
- 暴露工具：
  - `mypaper_retrieve_knowledge(query: str)`
  - `mypaper_web_search(query: str, count: int = 5)`
  - `mypaper_get_current_time(timezone: str = "Asia/Shanghai")`

MCP 返回统一结构：

```json
{
  "ok": true,
  "data": {},
  "error": "",
  "error_code": "",
  "summary": "",
  "truncated": false,
  "truncated_from": 0,
  "trace": {
    "run_id": "...",
    "trace_path": "..."
  }
}
```

## 安装依赖

建议使用项目当前的 conda 环境：

```powershell
cd F:\longchain\mypaperweb
D:\anaconda3\envs\deepagents\python.exe -m pip install -r requirements.txt
```

只安装 MCP SDK：

```powershell
D:\anaconda3\envs\deepagents\python.exe -m pip install mcp
```

验证 MCP SDK：

```powershell
D:\anaconda3\envs\deepagents\python.exe -c "from mcp.server.fastmcp import FastMCP; print('mcp ok')"
```

看到 `mcp ok` 即表示依赖可用。

## 使用 MCP Inspector 测试

启动 Inspector：

```powershell
cd F:\longchain\mypaperweb\app
npx -y @modelcontextprotocol/inspector D:\anaconda3\envs\deepagents\python.exe mcp_server.py
```

启动后，终端会输出一个带 token 的 URL，例如：

```text
http://localhost:6274/?MCP_PROXY_AUTH_TOKEN=xxxxxx
```

必须复制完整 URL 打开，不能只打开 `http://localhost:6274`。

进入页面后：

1. 点击 `Connect`。
2. 打开 `Tools`。
3. 点击 `List Tools`。
4. 确认能看到三个工具：
   - `mypaper_retrieve_knowledge`
   - `mypaper_web_search`
   - `mypaper_get_current_time`

## 推荐测试顺序

### 1. 当前时间工具

工具：

```text
mypaper_get_current_time
```

参数：

```json
{
  "timezone": "Asia/Shanghai"
}
```

预期：

```json
{
  "ok": true,
  "error": "",
  "error_code": ""
}
```

返回里应该包含 `trace.run_id`。

### 2. Web Search 工具

工具：

```text
mypaper_web_search
```

参数：

```json
{
  "query": "LLM Agent evaluation",
  "count": 3
}
```

预期：

- `ok` 为 `true`
- `data.results` 有搜索结果
- `snippet` 已被清洗和截断，不应再出现大量登录链接、图片链接、页面导航文本
- `summary` 类似 `Found 3 web search results, provider=tavily`

### 3. 参数校验

工具：

```text
mypaper_web_search
```

参数：

```json
{
  "query": "agent",
  "count": 11
}
```

预期：

```json
{
  "ok": false,
  "error_code": "INVALID_ARGS"
}
```

这说明 MCP 适配层的输入保护生效。

### 4. 知识库检索工具

工具：

```text
mypaper_retrieve_knowledge
```

参数：

```json
{
  "query": "RAG evaluation"
}
```

注意：该工具依赖 Milvus 和本地知识库。如果 Milvus 没启动，返回结构化失败是正常的；关键是 MCP Server 不应该崩溃。

## 查看 Trace

每次 MCP 调用都会写入 Run Trace。返回结果中会包含：

```json
{
  "trace": {
    "run_id": "...",
    "trace_path": "F:\\longchain\\mypaperweb\\app\\data\\run_traces\\mcp\\xxx.json"
  }
}
```

查看 trace 文件：

```powershell
Get-ChildItem F:\longchain\mypaperweb\app\data\run_traces\mcp -Recurse
```

打开某个 trace：

```powershell
Get-Content F:\longchain\mypaperweb\app\data\run_traces\mcp\<run_id>.json
```

关键字段：

```json
{
  "route": "mcp",
  "session_id": "mcp",
  "metadata": {
    "source": "mcp",
    "mcp_tool_name": "mypaper_get_current_time",
    "internal_tool_name": "get_current_time"
  },
  "steps": [
    {
      "step_type": "mcp_tool",
      "status": "completed",
      "latency_ms": 123,
      "input": {},
      "output": {}
    }
  ]
}
```

## 常见问题

### Connection Error: proxy token is incorrect

通常是浏览器打开了旧页面或没有带 token 的 URL。

处理方式：

1. 关闭旧 Inspector 页面。
2. 关闭旧终端。
3. 重新运行 Inspector 命令。
4. 复制终端里最新的完整 URL，包括 `MCP_PROXY_AUTH_TOKEN`。

### MCP error -32001: Request timed out

通常是工具冷启动或外部服务响应慢。

当前已优化 MCP 冷启动：`mypaper_get_current_time` 不再加载 RAG/Milvus 重服务。如果仍超时：

- 先测 `mypaper_get_current_time`
- 再测非法参数 case，例如 `count: 11`
- 最后测依赖外部服务的 `web_search` 或 `retrieve_knowledge`

### Web Search 返回内容很长

MCP 层已对 `web_search` 做清洗：

- 去掉 Markdown 图片
- 去掉 Markdown 链接外壳
- 去掉登录、导航、隐私条款等噪声
- 限制 snippet 长度

如果仍然很长，优先检查返回是否来自非标准 provider 或底层服务字段结构发生变化。

### Milvus 未启动

`mypaper_retrieve_knowledge` 依赖 Milvus。Milvus 未启动时，MCP 应返回：

```json
{
  "ok": false,
  "error_code": "TOOL_EXECUTION_ERROR"
}
```

这是结构化失败，不代表 MCP Server 本身失败。

## 面试讲法

可以这样描述：

```text
我没有把 MCP 当成另一个工具系统重写，而是在现有 ToolRegistry、ToolWrapper、ToolResult 上做了一层协议适配。MCP Server 负责工具发现和 stdio 协议，mcp_tools.py 负责参数校验、工具名映射、结构化返回、输出清洗和 trace 记录。

这样 Agent 内部工具调用和外部 MCP 客户端调用复用同一套工具执行链路。后续如果要增加工具，只需要在注册表里补元数据，并决定是否暴露到 MCP，而不是维护两套逻辑。

另外每次 MCP 调用都会进入 RunTraceService，step_type 是 mcp_tool，可以记录参数、耗时、结果摘要和错误码。所以这个项目不只是能调工具，还能观测、排错和评估。
```
