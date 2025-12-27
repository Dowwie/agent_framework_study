# Fathom Sandbox Protocol v1.0

A WebSocket-based protocol for secure, isolated code execution in agent frameworks.

## Overview

| Property | Value |
|----------|-------|
| Version | 1.0 |
| Transport | WebSocket |
| Encoding | JSON |
| Output mode | Streaming |
| Session model | Stateless |

## Design Principles

1. **Stateless execution** — Each execution gets a fresh, isolated environment
2. **Streaming output** — stdout/stderr streamed as produced, not buffered
3. **Explicit acknowledgment** — Server confirms receipt before execution starts
4. **Versioned from day one** — Protocol version in every message enables evolution
5. **Structured errors** — Enumerated error codes for programmatic handling

## Message Format

Every message follows this envelope structure:

```json
{
  "v": 1,
  "type": "<message_type>",
  "id": "<execution_id>",
  "ts": "<ISO8601_timestamp>",
  ...type-specific fields
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `v` | integer | Yes | Protocol version |
| `type` | string | Yes | Message type identifier |
| `id` | string | Conditional | Execution ID (required for execution-related messages) |
| `ts` | string | Yes | ISO8601 timestamp with milliseconds |

## Client → Sandbox Messages

### `execute` — Start Code Execution

```json
{
  "v": 1,
  "type": "execute",
  "id": "exec_a1b2c3d4",
  "ts": "2025-12-27T11:30:00.000Z",
  "language": "python",
  "code": "print('hello world')",
  "stdin": null,
  "env": {
    "API_KEY": "..."
  },
  "limits": {
    "timeout_ms": 30000,
    "memory_mb": 256,
    "cpu_shares": 512,
    "max_output_bytes": 1048576
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `language` | enum | Yes | `python`, `javascript`, `shell`, `elixir` |
| `code` | string | Yes | Source code to execute |
| `stdin` | string | No | Standard input to provide |
| `env` | object | No | Environment variables (key-value pairs) |
| `limits.timeout_ms` | integer | Yes | Maximum execution time in milliseconds |
| `limits.memory_mb` | integer | Yes | Maximum memory allocation in MB |
| `limits.cpu_shares` | integer | No | CPU resource share (default: 512) |
| `limits.max_output_bytes` | integer | No | Max stdout+stderr size (default: 1MB) |

### `cancel` — Abort Execution

```json
{
  "v": 1,
  "type": "cancel",
  "id": "exec_a1b2c3d4",
  "ts": "2025-12-27T11:30:05.000Z"
}
```

Requests cancellation of a running execution. The sandbox SHOULD terminate the execution promptly and respond with `status: cancelled`.

### `ping` — Health Check

```json
{
  "v": 1,
  "type": "ping",
  "ts": "2025-12-27T11:30:00.000Z"
}
```

Requests a health check response. No `id` field required.

## Sandbox → Client Messages

### `ack` — Execution Accepted

Sent immediately after `execute` received, before execution begins.

```json
{
  "v": 1,
  "type": "ack",
  "id": "exec_a1b2c3d4",
  "ts": "2025-12-27T11:30:00.001Z"
}
```

The `ack` confirms the request was received and queued. Execution has not yet started. This allows clients to distinguish "request not received" from "execution failed to start."

### `status` — Execution State Change

```json
{
  "v": 1,
  "type": "status",
  "id": "exec_a1b2c3d4",
  "ts": "2025-12-27T11:30:00.010Z",
  "status": "running"
}
```

| Status | Terminal | Description |
|--------|----------|-------------|
| `running` | No | Execution started |
| `completed` | Yes | Execution finished normally |
| `failed` | Yes | Execution encountered error |
| `cancelled` | Yes | Execution was cancelled by client |
| `timeout` | Yes | Execution exceeded time limit |
| `oom` | Yes | Execution exceeded memory limit |

### `stdout` / `stderr` — Output Streams

```json
{
  "v": 1,
  "type": "stdout",
  "id": "exec_a1b2c3d4",
  "ts": "2025-12-27T11:30:00.100Z",
  "data": "hello world\n"
}
```

- `type` is either `stdout` or `stderr`
- `data` contains UTF-8 encoded output
- Chunks may arrive in any order relative to each other
- Large outputs may be split across multiple messages
- Empty `data` fields are valid (e.g., for newlines)

### `result` — Execution Complete

Sent after a terminal `status` message.

```json
{
  "v": 1,
  "type": "result",
  "id": "exec_a1b2c3d4",
  "ts": "2025-12-27T11:30:01.500Z",
  "exit_code": 0,
  "duration_ms": 1500,
  "resource_usage": {
    "peak_memory_mb": 45,
    "cpu_time_ms": 120
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `exit_code` | integer | Process exit code (`null` if killed by signal) |
| `duration_ms` | integer | Wall-clock execution time |
| `resource_usage` | object | Optional resource consumption metrics |

### `error` — Execution Error

Sent when execution cannot complete due to sandbox/infrastructure issues.

```json
{
  "v": 1,
  "type": "error",
  "id": "exec_a1b2c3d4",
  "ts": "2025-12-27T11:30:00.500Z",
  "code": "LANGUAGE_NOT_SUPPORTED",
  "message": "Language 'rust' is not available in this sandbox",
  "retryable": false
}
```

| Field | Type | Description |
|-------|------|-------------|
| `code` | string | Enumerated error code (see Error Codes) |
| `message` | string | Human-readable error description |
| `retryable` | boolean | Whether the client should retry |

### `pong` — Health Check Response

```json
{
  "v": 1,
  "type": "pong",
  "ts": "2025-12-27T11:30:00.001Z",
  "load": {
    "active_executions": 3,
    "queue_depth": 0
  }
}
```

The `load` field is optional and provides current sandbox load information.

## Error Codes

| Code | Category | Retryable | Description |
|------|----------|-----------|-------------|
| `TIMEOUT` | Resource | No | Execution exceeded time limit |
| `OOM` | Resource | No | Execution exceeded memory limit |
| `OUTPUT_LIMIT` | Resource | No | Output exceeded `max_output_bytes` |
| `LANGUAGE_NOT_SUPPORTED` | Protocol | No | Requested language unavailable |
| `INVALID_REQUEST` | Protocol | No | Malformed request structure |
| `UNKNOWN_EXECUTION` | Protocol | No | Cancel for unknown execution ID |
| `SANDBOX_OVERLOADED` | Infrastructure | Yes | Sandbox at capacity, try later |
| `INTERNAL_ERROR` | Infrastructure | Yes | Unexpected sandbox failure |
| `NETWORK_ERROR` | Infrastructure | Yes | Sandbox network connectivity issue |

## Message Sequences

### Successful Execution

```
Client                    Sandbox
  |                         |
  |-------- execute ------->|
  |<-------- ack -----------|
  |<------- status:running -|
  |<------- stdout ---------|
  |<------- stdout ---------|
  |<------- stderr ---------|
  |<------ status:completed-|
  |<------- result ---------|
  |                         |
```

### Execution Timeout

```
Client                    Sandbox
  |                         |
  |-------- execute ------->|
  |<-------- ack -----------|
  |<------- status:running -|
  |<------- stdout ---------|
  |          ... time passes ...
  |<------ status:timeout --|
  |<------- result ---------|
  |                         |
```

### Client-Initiated Cancel

```
Client                    Sandbox
  |                         |
  |-------- execute ------->|
  |<-------- ack -----------|
  |<------- status:running -|
  |-------- cancel -------->|
  |<----- status:cancelled -|
  |<------- result ---------|
  |                         |
```

### Infrastructure Error

```
Client                    Sandbox
  |                         |
  |-------- execute ------->|
  |<-------- ack -----------|
  |<------- status:running -|
  |          ... sandbox issue ...
  |<------- error ----------|
  |         (INTERNAL_ERROR)|
  |                         |
```

### Request Rejected

```
Client                    Sandbox
  |                         |
  |-------- execute ------->|
  |<------- error ----------|
  |   (LANGUAGE_NOT_SUPPORTED)
  |                         |
```

No `ack` is sent if the request is immediately rejected.

## Connection Management

### Authentication

Clients SHOULD authenticate during the WebSocket upgrade handshake:

```
GET /ws HTTP/1.1
Upgrade: websocket
Authorization: Bearer <token>
X-Protocol-Version: 1
```

### Reconnection

Clients SHOULD implement reconnection with exponential backoff:

1. On disconnect, attempt immediate reconnection (once)
2. If immediate reconnection fails, wait `backoff_ms` and retry
3. Double `backoff_ms` on each failure (cap at 30 seconds)
4. Reset backoff on successful connection

### Pending Executions on Disconnect

If the connection closes while executions are pending:

- Client SHOULD treat pending executions as failed with a retryable error
- Sandbox SHOULD terminate orphaned executions after a grace period
- Executions are NOT automatically resumed on reconnection (stateless model)

## Versioning

- Clients MUST include `v` field in all messages
- Sandbox SHOULD reject messages with unsupported version
- Sandbox MAY support multiple protocol versions simultaneously
- Breaking changes require version increment

### Version Negotiation

Clients indicate supported version via `X-Protocol-Version` header during WebSocket upgrade. Sandbox responds with its supported version. If incompatible, sandbox closes connection with appropriate error.

## Security Considerations

### Execution Isolation

Each execution MUST run in an isolated environment:

- Separate process/container/WASM instance
- No access to host filesystem (except explicitly mounted paths)
- No network access (unless explicitly enabled)
- Resource limits strictly enforced

### Input Validation

Sandbox MUST validate:

- `language` is in supported set
- `code` does not exceed maximum size
- `limits` are within allowed ranges
- `env` keys/values do not exceed size limits

### Sensitive Data

- Sandbox SHOULD NOT log `code` or `env` contents
- Sandbox SHOULD NOT persist execution artifacts beyond session
- Client SHOULD NOT include secrets in `env` unless necessary

## Implementation Notes

### Client-Side Event Accumulation

```python
class Accumulator:
    def __init__(self, execution_id):
        self.execution_id = execution_id
        self.status = None
        self.stdout = ""
        self.stderr = ""
        self.exit_code = None
        self.duration_ms = None

    def apply(self, event):
        match event["type"]:
            case "stdout": self.stdout += event["data"]
            case "stderr": self.stderr += event["data"]
            case "status": self.status = event["status"]
            case "result":
                self.exit_code = event["exit_code"]
                self.duration_ms = event["duration_ms"]

    def is_terminal(self):
        return self.status in ["completed", "failed", "timeout", "oom", "cancelled"]
```

### Sandbox Implementation Considerations

- Use process isolation (containers, WASM, VMs) for security
- Implement watchdog for timeout enforcement
- Stream output via non-blocking I/O
- Pre-warm language runtimes for lower latency
- Consider execution queuing for load management

## References

- Designed for the Fathom Agent Framework
- Session log: `docs/elixir-sessions/2025-12-27-1100.md`
