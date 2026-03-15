# SSE 协议说明

## 本文范围

本文只描述 `POST /chat/stream` 的流式事件协议，不描述其它 HTTP 接口。

## 1. 基础格式

响应头：

- `Content-Type: text/event-stream`

每条事件固定格式：

```text
event: message
data: { ...json envelope... }
```

`event` 字段固定为 `message`。

## 2. Envelope 结构

```json
{
  "type": "meta",
  "seq": 1,
  "request_id": "...",
  "ts": "2026-03-11T15:20:00.000000Z",
  "employee_id": "1",
  "session_id": "employee-1",
  "payload": {}
}
```

字段说明：

- `type`：业务事件类型
- `seq`：单请求内自增序号
- `request_id`：请求标识
- `ts`：事件时间戳（UTC）
- `employee_id`：当前数字员工编号
- `session_id`：当前员工绑定会话 ID
- `payload`：业务负载

## 3. 事件类型

- `meta`
- `tool_call`
- `tool_result`
- `assistant_final`
- `memory_status`
- `done`
- `error`

## 4. 推荐处理顺序

常见顺序如下：

1. `meta`
2. `tool_call`（可多次）
3. `tool_result`（可多次）
4. `assistant_final`
5. `memory_status`
6. `done`

异常时会发送 `error`，然后 `done`。

常见 `error` 场景包括：

- 工具调用异常
- 模型请求异常
- 刷盘期间 `buffer` 超过上限（`buffer_limit`）导致拒绝新消息

## 5. 前端解析建议

1. 逐块读取流并按 `\n\n` 分帧
2. 提取 `data:` 行并解析 JSON
3. 按 `envelope.type` 分发渲染
4. 忽略未知 `type`，避免单次异常事件影响主流程

## 6. 示例

```json
{
  "type": "tool_call",
  "seq": 3,
  "request_id": "ab12cd34",
  "ts": "2026-03-11T15:21:03.001000Z",
  "employee_id": "2",
  "session_id": "employee-2",
  "payload": {
    "event": "tool_call",
    "tool_name": "read_memory_file",
    "arguments": {
      "file_name": "memory.md"
    }
  }
}
```
