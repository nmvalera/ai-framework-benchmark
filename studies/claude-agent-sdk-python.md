# Claude Agent SDK Py — Benchmark Study

> **Repo**: https://github.com/anthropics/claude-agent-sdk-python
> **Commit studied**: `c352a509929a712de65637cbafafcc3a1e3ba4f6`
> **Cloned at**: `benchmarked-stacks/claude-agent-sdk-python/`
> **Studied on**: 2026-05-16

## TL;DR

- **The run loop is not in Python.** This SDK is a ~10 kLOC Python facade. The actual agent loop (turn boundaries, tool dispatch, planner, hook firing, system-prompt assembly, compaction, skill discovery, sub-agent fan-out, model routing) runs in the **bundled Claude Code CLI** — a Node.js binary spawned via `subprocess` over a stdin/stdout JSON control protocol (`src/claude_agent_sdk/_internal/transport/subprocess_cli.py:225`). The Python side is a transport, a typed-message parser, hook callback router, and an in-process MCP host. **You cannot fork the loop without forking Claude Code.**
- **Hooks are excellent and the best in the comparison.** 10 lifecycle events (`PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `UserPromptSubmit`, `Stop`, `SubagentStop`, `PreCompact`, `Notification`, `SubagentStart`, `PermissionRequest` — `types.py:259-270`), with strongly-typed inputs per event, and outputs that can mutate tool input (`updatedInput`), replace tool output (`updatedToolOutput`), inject `additionalContext`, block (`continue_=False`), or defer the tool (`permissionDecision: "defer"`). Matchers fire **concurrently** per event — explicitly documented (`types.py:1766-1771`).
- **Forcing tool arguments works via `can_use_tool` (`PermissionResultAllow.updated_input`) or `PreToolUse` hook (`updatedInput`).** Both are out-of-band Python callbacks invoked via the control protocol — so `tenantId` injection is feasible without trusting the LLM. Concretely usable for our multi-tenant case (`types.py:233-239`, `query.py:415-423`).
- **Multi-tenant scoping is filesystem-shaped, not API-shaped.** Skills, sub-agents, slash commands, plugins, and CLAUDE.md all load from `.claude/` directories on disk. There is no programmatic `registerSkill(tenantID, ...)` API. To scope to a tenant, you must materialize a per-tenant `.claude/` tree and point the subprocess at it via `cwd` + `CLAUDE_CONFIG_DIR` + `setting_sources` + `plugin-dir`. Skills option (`types.py:1812-1830`) is only a "context filter" over already-on-disk skills — explicitly documented as "not a sandbox".
- **`max_budget_usd` is real, first-party, and unique in the comparison.** Implemented as a CLI flag (`subprocess_cli.py:262-263`) that the CLI evaluates after each turn. On overrun the run ends with `ResultMessage.subtype == "error_max_budget_usd"` (`examples/max_budget_usd.py:72`). Cost itself (`total_cost_usd`) is exposed on every `ResultMessage`.
- **Native MCP everywhere.** External stdio/SSE/HTTP MCP servers AND in-process `SdkMcpServer` are supported. In-process MCP tools are bridged through the control protocol (`query.py:548-721`), so a Python `@tool`-decorated function runs in our process with full closure access — same effect as a native SDK tool.
- **Per-stack one-liners**:
  - **Skills**: filesystem-only, no programmatic registration; multi-tenant requires per-tenant `.claude/skills/` trees.
  - **Sub-agents**: first-class, configurable inline via `AgentDefinition`, dispatched by the CLI's built-in `Task` tool with native parallelism (`types.py:82-101`).
  - **Multi-tenancy**: forcing tool args is supported; visible toolset filtering is supported via `tools`/`allowed_tools`; tenant context propagation is BYO (closure capture into hook callbacks).
  - **Hooks**: 10 events, can mutate input/output, can block/defer/branch. Best-in-class.
  - **API**: library-only, no HTTP server. Control protocol is JSON-over-stdio with the CLI subprocess.
  - **Observability**: token counts on every `AssistantMessage.usage`, cost on `ResultMessage.total_cost_usd`, OTel context auto-propagated to the CLI subprocess (`subprocess_cli.py:441-462`), `get_context_usage()` exposes a full per-category breakdown.

## 1. Message Types & Event Taxonomy

The SDK exposes **two layers of messages** plus a third hidden layer of control-protocol frames:

1. **Wire layer (CLI ↔ Python)** — line-delimited JSON over the CLI subprocess's stdout. Each line is a discriminated dict with `type ∈ {"user", "assistant", "system", "result", "stream_event", "rate_limit_event", "control_request", "control_response", "control_cancel_request", "transcript_mirror"}`. Control / transcript frames are peeled off by the read loop and never surfaced.
2. **SDK message layer (Python public)** — typed dataclasses returned by the async iterator. Defined in `src/claude_agent_sdk/types.py`. There is no separate "UI message" layer; the SDK message layer is what your application iterates.

Concrete public message dataclasses (`types.py:1014-1268`):

| Type | Purpose |
|---|---|
| `UserMessage` | A user turn — text or list of `ContentBlock`. `parent_tool_use_id` flags sub-agent injected turns. |
| `AssistantMessage` | A model turn. Holds `content: list[ContentBlock]`, `model`, `usage`, `stop_reason`, `session_id`. |
| `SystemMessage` | Lifecycle/init/notice with `subtype` discriminator. Subclasses for specific subtypes (see below). |
| `TaskStartedMessage` / `TaskProgressMessage` / `TaskNotificationMessage` | Sub-agent lifecycle (the CLI's `Task` tool) — `task_id`, `description`, `usage`, `status`. |
| `MirrorErrorMessage` | SDK-synthesized when `SessionStore.append()` failed; surfaces a dropped batch to the caller. |
| `HookEventMessage` | Hook lifecycle events when `include_hook_events=True`. Subtype is `hook_started` or `hook_response`. |
| `ResultMessage` | Terminal per-turn message. Carries `is_error`, `num_turns`, `total_cost_usd`, `usage`, `model_usage`, `stop_reason`, `permission_denials`, `deferred_tool_use`, `api_error_status`. |
| `StreamEvent` | Partial assistant streaming events (when `include_partial_messages=True`) — raw Anthropic API stream event in `event`. |
| `RateLimitEvent` | API rate-limit transitions (`allowed` → `allowed_warning` → `rejected`). |

`ContentBlock` is a discriminated union: `TextBlock | ThinkingBlock | ToolUseBlock | ToolResultBlock | ServerToolUseBlock | ServerToolResultBlock` (`types.py:993-1000`). `ServerTool*` blocks are for server-executed tools (advisor, web_search, web_fetch, code_execution …) — the caller never returns a result for those (`types.py:953-991`).

The discriminated `Message` union (`types.py:1261-1268`):

```python
Message = (
    UserMessage
    | AssistantMessage
    | SystemMessage
    | ResultMessage
    | StreamEvent
    | RateLimitEvent
)
```

**Messages vs. events**: there is no separate event taxonomy. Everything is a message in a single ordered stream. The "stream-event vs. turn-event vs. tool-event" categories you'd expect in Mastra/Vercel are all expressed as message-with-subtype on a single async iterator:

- Stream event = `StreamEvent`
- Turn boundary = `ResultMessage` (one per turn)
- Tool event = `AssistantMessage` containing a `ToolUseBlock`, then a `UserMessage` containing a `ToolResultBlock` (matched by `tool_use_id`)
- Session lifecycle = `SystemMessage(subtype="init")` at start; the CLI subprocess exit ends iteration
- Hook event = `HookEventMessage` when opt-in
- Sub-agent lifecycle = `TaskStartedMessage` / `TaskProgressMessage` / `TaskNotificationMessage`

**Hidden third layer — control protocol frames** (`types.py:1942-2043`): `SDKControlRequest` / `SDKControlResponse` carry `subtype ∈ {initialize, interrupt, can_use_tool, hook_callback, mcp_message, set_permission_mode, set_model, rewind_files, mcp_reconnect, mcp_toggle, stop_task, get_context_usage, mcp_status}`. These are JSON frames on stdout/stdin that implement bidirectional RPC between the Python SDK and the Node CLI. The Python read loop routes them to `_handle_control_request` (`query.py:375-499`) and never yields them to the caller.

Canonical type-definition file: **`src/claude_agent_sdk/types.py`** (2043 lines, single source of truth). Parser: **`src/claude_agent_sdk/_internal/message_parser.py`** (319 lines, drives the `match` on `type`/`subtype` to produce typed dataclasses).

## 2. Agent Run Loop

**Where the loop actually runs**: in the **Node.js Claude Code CLI subprocess**, NOT in Python. The Python entrypoint is a transport + control-protocol shim. The actual model-call → tool-call → tool-result → next-model-call cycle, system prompt assembly, permission evaluation, skill discovery, compaction, and Task sub-agent dispatch all execute in the CLI. This is the most important architectural fact about this SDK and shapes every other question below.

### Entrypoints

Two:

```python
# src/claude_agent_sdk/query.py:11
async def query(
    *,
    prompt: str | AsyncIterable[dict[str, Any]],
    options: ClaudeAgentOptions | None = None,
    transport: Transport | None = None,
) -> AsyncIterator[Message]:
```

```python
# src/claude_agent_sdk/client.py:67
class ClaudeSDKClient:
    def __init__(self, options=None, transport=None): ...
    async def connect(self, prompt=None) -> None: ...
    async def query(self, prompt, session_id="default") -> None: ...
    async def receive_messages(self) -> AsyncIterator[Message]: ...
    async def receive_response(self) -> AsyncIterator[Message]: ...  # iterates until next ResultMessage
    async def interrupt(self) -> None: ...
    async def set_permission_mode(self, mode) -> None: ...
    async def set_model(self, model: str | None) -> None: ...
    async def stop_task(self, task_id: str) -> None: ...
    async def disconnect(self) -> None: ...
```

`query()` is one-shot (single prompt, drains the iterator, exits). `ClaudeSDKClient` is bidirectional (keep stdin open, send multiple prompts, interrupt mid-flight).

### Per-iteration behavior

The Python "loop" is just an async generator over stdout JSON frames (`query.py:247-373`):

```python
# src/claude_agent_sdk/_internal/query.py:247
async def _read_messages(self) -> None:
    """Read messages from transport and route them."""
    try:
        async for message in self.transport.read_messages():
            if self._closed:
                break
            msg_type = message.get("type")

            if msg_type == "control_response":
                # … route to pending control request waiter
                continue
            elif msg_type == "control_request":
                # … spawn handler for incoming hook/permission/mcp request
                self._spawn_control_request_handler(request)
                continue
            elif msg_type == "control_cancel_request":
                # … cancel inflight control task
                continue
            elif msg_type == "transcript_mirror":
                # … peel off and hand to SessionStore batcher
                continue

            if msg_type == "result":
                # flush transcript mirror; signal first-result event
                if self._transcript_mirror_batcher is not None:
                    await self._transcript_mirror_batcher.flush()
                self._first_result_event.set()
            # everything else → enqueued for the consumer iterator
            await self._message_send.send(message)
```

The actual per-iteration logic of the agent (call model → parse tool calls → run permission/hook gate → dispatch tool → collect result → re-prompt model) happens **inside the CLI subprocess**. We only see the result frames stream by.

### Turn concept

A "turn" is defined by `ResultMessage`. The CLI emits exactly one `ResultMessage` per user prompt. `ResultMessage.num_turns` is also reported (`types.py:1144-1167`), so the CLI's internal concept counts assistant↔tool exchanges within a single user prompt. `max_turns` (`types.py:1653-1657`) caps the CLI's internal turn loop and triggers an `error_max_turns` result on overrun.

### Sessions / threads

Session state is durable in **two places**:

1. **The CLI's local JSONL transcript** at `~/.claude/projects/<sanitized-cwd>/<session_id>.jsonl`. The CLI is the only writer. Re-spawning with `--resume <id>` reloads it.
2. **Optional external `SessionStore` mirror** (`types.py:1370-1487`). When set on `ClaudeAgentOptions.session_store`, the CLI emits `transcript_mirror` frames on stdout that the Python SDK collects and forwards to your `store.append(key, entries)`. The store is **not** a primary write path — it's a mirror; the local JSONL is still the source of truth.

`SessionKey` (`types.py:1276-1295`) has `project_key`, `session_id`, optional `subpath`. The doc explicitly states: *"Multi-tenant deployments should set this to a tenant ID or project name"*. Reference adapters for Postgres, Redis, S3 are in `examples/session_stores/`.

### Persistence timing

```python
# src/claude_agent_sdk/_internal/query.py:296-303
# Track results for proper stream closure
if msg_type == "result":
    # Flush pending transcript mirror entries before yielding
    # result so consumers observing the result can rely on the
    # SessionStore being up to date for this turn.
    if self._transcript_mirror_batcher is not None:
        await self._transcript_mirror_batcher.flush()
    self._first_result_event.set()
```

Default is **batched, flush-on-turn-end** (or eager with `session_store_flush="eager"`). Local JSONL is written by the CLI on every entry. The SDK guarantees the external store is up-to-date by the time you observe a `ResultMessage`. Backpressure: 500 entries / 1 MiB max-pending thresholds (`transcript_mirror_batcher.py:26-27`), with bounded retry (3 attempts, 0.2s/0.8s backoff) before dropping a batch and surfacing it as `MirrorErrorMessage`.

### Event emission mechanism

`anyio` memory-object stream (`asyncio` `Queue` equivalent) with `max_buffer_size=100` (`query.py:121-123`). The transport read loop pushes; `receive_messages()` pops. Backpressure is via the bounded buffer — a slow consumer will block the read loop after 100 buffered messages.

### HITL pause/resume

There is **no explicit "the loop is paused awaiting verdict" state** that the caller can observe. Instead, when the CLI hits a tool that requires permission and a `can_use_tool` callback is registered, the CLI sends a `control_request` of subtype `can_use_tool` over stdout. The Python read loop spawns a handler that awaits the user's `CanUseTool` callback and writes back a `control_response`:

```python
# src/claude_agent_sdk/_internal/query.py:384-436
if subtype == "can_use_tool":
    # ...
    response = await self.can_use_tool(
        permission_request["tool_name"],
        permission_request["input"],
        context,
    )
    if isinstance(response, PermissionResultAllow):
        response_data = {
            "behavior": "allow",
            "updatedInput": (
                response.updated_input
                if response.updated_input is not None
                else original_input
            ),
        }
        # …
    elif isinstance(response, PermissionResultDeny):
        response_data = {"behavior": "deny", "message": response.message}
```

So HITL "pause" is: the CLI is internally blocked waiting on a `control_response`. From the Python side, the iterator keeps emitting earlier messages but you won't see a new `AssistantMessage` until you reply. Cross-request HITL (where the verdict comes from another HTTP call hours later) requires you to keep the `ClaudeSDKClient` alive in the process for that long — there's no on-disk "deferred tool calls" queue you can pick up later. **The CLI subprocess must remain alive across the HITL window.**

A weaker form of HITL exists via `PreToolUse` hook returning `permissionDecision: "defer"` (`types.py:412-419`) — the CLI then ends the turn with `ResultMessage.deferred_tool_use` set (`types.py:1131-1141`) so a *different* process can later inspect what was deferred and decide to resume. This is the closest the SDK gets to durable HITL.

### Interrupt / cancel

`ClaudeSDKClient.interrupt()` sends a `control_request` with `subtype: "interrupt"` (`query.py:731-733`):

```python
async def interrupt(self) -> None:
    """Send interrupt control request."""
    await self._send_control_request({"subtype": "interrupt"})
```

The CLI handles the actual mid-LLM-call / mid-tool-call cancellation. There is **no Python `asyncio.CancelScope` for the run** — closing the iterator just kills the subprocess (`subprocess_cli.py:545-600`, with a 5s graceful + SIGTERM + 5s + SIGKILL fallback). An `atexit` handler also kills all live CLI subprocesses on parent Python exit (`subprocess_cli.py:37-47`) to prevent orphaned `claude` processes.

`ClaudeSDKClient.stop_task(task_id)` cancels a specific sub-agent task by ID (`client.py:450-471`).

## 3. Multi-tenancy & Arbitrary Context

### The full input struct

`ClaudeAgentOptions` is a single dataclass with **~50 fields** (`types.py:1578-1939`). The big ones:

```python
# src/claude_agent_sdk/types.py:1578 (truncated to key fields)
@dataclass
class ClaudeAgentOptions:
    tools: list[str] | ToolsPreset | None = None
    allowed_tools: list[str] = field(default_factory=list)
    disallowed_tools: list[str] = field(default_factory=list)
    system_prompt: str | SystemPromptPreset | SystemPromptFile | None = None
    mcp_servers: dict[str, McpServerConfig] | str | Path = field(default_factory=dict)
    strict_mcp_config: bool = False
    permission_mode: PermissionMode | None = None
    continue_conversation: bool = False
    resume: str | None = None
    session_id: str | None = None
    max_turns: int | None = None
    max_budget_usd: float | None = None
    model: str | None = None
    fallback_model: str | None = None
    betas: list[SdkBeta] = field(default_factory=list)
    cwd: str | Path | None = None
    cli_path: str | Path | None = None
    settings: str | None = None
    add_dirs: list[str | Path] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    extra_args: dict[str, str | None] = field(default_factory=dict)
    stderr: Callable[[str], None] | None = None
    can_use_tool: CanUseTool | None = None
    hooks: dict[HookEvent, list[HookMatcher]] | None = None
    user: str | None = None
    include_partial_messages: bool = False
    include_hook_events: bool = False
    fork_session: bool = False
    agents: dict[str, AgentDefinition] | None = None
    setting_sources: list[SettingSource] | None = None
    skills: list[str] | Literal["all"] | None = None
    sandbox: SandboxSettings | None = None
    plugins: list[SdkPluginConfig] = field(default_factory=list)
    thinking: ThinkingConfig | None = None
    effort: EffortLevel | None = None
    output_format: dict[str, Any] | None = None
    enable_file_checkpointing: bool = False
    session_store: SessionStore | None = None
    session_store_flush: SessionStoreFlushMode = "batched"
    task_budget: TaskBudget | None = None
    permission_prompt_tool_name: str | None = None
```

There is **no field for arbitrary opaque user context** to be passed *into* tool handlers or hooks. To pass tenant context you must close over it in your Python callbacks (hooks, `can_use_tool`, `@tool` handlers) — they're regular Python coroutines, so closure capture works fine.

### Context propagation into tool calls

For an **SDK MCP tool** (in-process, decorated with `@tool`), the handler signature is just `Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]` (`__init__.py:162`):

```python
# src/claude_agent_sdk/__init__.py:196-220
>>> @tool("greet", "Greet a user", {"name": str})
... async def greet(args):
...     return {"content": [{"type": "text", "text": f"Hello, {args['name']}!"}]}
```

**The handler receives only the LLM-generated arguments.** No `RunContext`, no `ToolContext`, no tenant ID, no session ID, no caller-supplied closure. To get tenant context inside the tool you must capture it in Python closure scope at server construction time:

```python
def make_tools(tenant_id: str):
    @tool("list_dashboards", "List dashboards", {"limit": int})
    async def list_dashboards(args):
        # tenant_id captured from outer scope — never trusts the LLM
        rows = await db.fetch_for_tenant(tenant_id, args["limit"])
        return {"content": [{"type": "text", "text": json.dumps(rows)}]}
    return [list_dashboards]

server = create_sdk_mcp_server("my", tools=make_tools(tenant_id="acme"))
```

For an **external MCP tool** (stdio/SSE/HTTP), the tool runs out-of-process — only the LLM-generated args reach it. No SDK-level mechanism injects context.

For the **CLI's built-in tools** (Read, Write, Bash, Grep, Glob, etc.), the same applies — they run inside the CLI subprocess with whatever cwd / env you set when you spawned it.

### Forcing tool arguments from the harness

**Yes — two mechanisms.** Both are out-of-band Python callbacks invoked via the control protocol, so the LLM cannot bypass them.

**Mechanism A: `PreToolUse` hook with `updatedInput`** (`types.py:412-419`):

```python
async def inject_tenant(input_data, tool_use_id, context):
    # Hook fires before EVERY tool call
    tool_input = dict(input_data["tool_input"])
    tool_input["tenantId"] = current_tenant_id  # forced server-side
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "updatedInput": tool_input,
        }
    }

options = ClaudeAgentOptions(
    hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[inject_tenant])]},
)
```

**Mechanism B: `can_use_tool` callback with `PermissionResultAllow(updated_input=...)`** (`types.py:233-239`, dispatch site `query.py:415-423`):

```python
async def can_use_tool(tool_name, input, ctx):
    if tool_name == "query_dashboards":
        input = {**input, "tenantId": current_tenant_id}
    return PermissionResultAllow(updated_input=input)

options = ClaudeAgentOptions(
    can_use_tool=can_use_tool,
    permission_mode="default",  # ensures the callback is invoked
)
```

Caveat: `can_use_tool` only fires when the CLI's permission evaluation reaches "ask" — tools already allowed by `allowed_tools` or `permission_mode="bypassPermissions"` bypass it (`types.py:1748-1758`). `PreToolUse` hook fires on **every** tool call regardless of permission state, which is what you want for forced argument injection.

### Filtering visible tools

**Three layers, all explicit:**

1. **`tools`** (`types.py:1582-1591`) — base set: a `list[str]` of tool names, `[]` to disable all built-ins, or `{"type": "preset", "preset": "claude_code"}` for the default set. Sent as the `--tools` CLI flag (`subprocess_cli.py:241-250`).
2. **`allowed_tools`** (`types.py:1593-1603`) — auto-allow list; tools listed here run without permission prompt. Sent as `--allowedTools` (`subprocess_cli.py:256-257`).
3. **`disallowed_tools`** (`types.py:1666-1671`) — explicit deny: *"removed from the model's context"*. Sent as `--disallowedTools` (`subprocess_cli.py:265-266`).

To change the toolset **per session**, set these on `ClaudeAgentOptions` at construction. To change **mid-session**, there is no first-party `set_tools()` control request — but you can use `PreToolUse` hook to deny a tool conditionally with `permissionDecision: "deny"`. There is also `set_permission_mode()` to flip the whole mode (`client.py:319-344`) and `toggle_mcp_server(name, enabled)` to enable/disable an entire MCP server's tools (`client.py:424-448`).

### Resource scoping primitives

**The SDK's scoping mechanism is the filesystem.** Skills, sub-agents (`.claude/agents/*.md`), slash commands, plugins, MCP config, and CLAUDE.md memory all load from `setting_sources` (`types.py:1800-1810`): `user` (`~/.claude/`), `project` (`.claude/` in cwd), `local` (`.claude/settings.local.json`). The CLI subprocess inherits `cwd` and optionally `CLAUDE_CONFIG_DIR` (env var).

For our multi-tenant long-running-agent case, this means **per-tenant resource scoping requires:**

- A per-tenant filesystem tree: `tenants/<tid>/.claude/skills/...`, `tenants/<tid>/.claude/agents/...`
- Setting `options.cwd = tenants/<tid>` per request
- Setting `options.env["CLAUDE_CONFIG_DIR"] = tenants/<tid>/.claude` so credentials, projects, and the JSONL transcript live in the tenant tree
- Optionally `options.setting_sources=["project"]` to ignore the global user settings entirely

There is no in-memory `Registry` you can pass per-request that says "tenant acme sees skills X,Y; tenant bcm sees skills A,B" — the SDK's `skills` option (`types.py:1812-1830`) is a **filter** over what's already on disk. The documentation explicitly notes: *"This is a context filter, not a sandbox: unlisted skills are hidden from the model's listing and rejected by the Skill tool, but their files remain on disk and are reachable via Read/Bash. Do not store secrets in skill files."*

`SessionKey.project_key` (`types.py:1276-1295`) is the documented multi-tenant primitive for the **session store** specifically: *"Multi-tenant deployments should set this to a tenant ID or project name."* But that scopes session storage only, not the toolset/skills/agents the CLI can see.

## 4. Hook Capabilities

This SDK has the most comprehensive hook system in the comparison.

### Enumerated hook events (`types.py:259-270`)

```python
HookEvent = (
    Literal["PreToolUse"]
    | Literal["PostToolUse"]
    | Literal["PostToolUseFailure"]
    | Literal["UserPromptSubmit"]
    | Literal["Stop"]
    | Literal["SubagentStop"]
    | Literal["PreCompact"]
    | Literal["Notification"]
    | Literal["SubagentStart"]
    | Literal["PermissionRequest"]
)
```

Plus `SessionStart` (the input dict shows up in `SessionStartHookSpecificOutput` at `types.py:454`).

| Hook | Fires | Can mutate / block |
|---|---|---|
| `PreToolUse` | Before any tool dispatch (built-in or MCP). | `updatedInput`, `permissionDecision: "allow"\|"deny"\|"ask"\|"defer"`, `additionalContext`. Can block, divert, or defer the call. |
| `PostToolUse` | After tool returns successfully. | `updatedToolOutput` (replace tool output before it reaches the model), `additionalContext` (extra system message to model). |
| `PostToolUseFailure` | After tool raises / errors. | `additionalContext`, plus `continue_=False` + `stopReason` to halt. |
| `UserPromptSubmit` | When user prompt is received, before model call. | `additionalContext` injects pre-prompt context. Can block via `decision: "block"`. |
| `SessionStart` | At session init. | `additionalContext` injects a "current date / tenant / etc." preamble. |
| `Stop` | Before a turn-end. | `decision: "block"` to force the model to keep going. |
| `SubagentStop` | When a Task sub-agent finishes. | Same as `Stop`. |
| `SubagentStart` | When a Task sub-agent starts. | `additionalContext`. |
| `PreCompact` | Before context-window compaction. | `additionalContext` + manual/auto trigger discrimination. |
| `Notification` | CLI-emitted notifications. | `additionalContext`. |
| `PermissionRequest` | When permission prompt would be shown. | `decision: dict` — fully programmatic permission verdict. |

Hook output schema (`types.py:516-560`):

```python
# src/claude_agent_sdk/types.py:516
class SyncHookJSONOutput(TypedDict):
    continue_: NotRequired[bool]      # False stops the loop
    suppressOutput: NotRequired[bool]
    stopReason: NotRequired[str]
    decision: NotRequired[Literal["block"]]
    systemMessage: NotRequired[str]   # shown to the user
    reason: NotRequired[str]          # shown to the model
    hookSpecificOutput: NotRequired[HookSpecificOutput]
```

### Hook configuration

```python
# src/claude_agent_sdk/types.py:584
@dataclass
class HookMatcher:
    matcher: str | None = None    # tool-name pattern, e.g. "Bash" or "Write|Edit"
    hooks: list[HookCallback] = field(default_factory=list)
    timeout: float | None = None  # default 60s
```

Hooks are registered as `dict[HookEvent, list[HookMatcher]]` on `ClaudeAgentOptions.hooks`. The Python SDK registers callback IDs at `initialize`-time (`query.py:182-200`) — the CLI references them by ID in subsequent `hook_callback` control requests, and the Python side dispatches to the actual coroutine.

**Critical concurrency note** (`types.py:1766-1771`): multiple matchers registered on the same event are **dispatched concurrently** by the CLI. *"All `hook_callback` control requests for a given event fire in parallel, not sequentially. Design each hook to be independent; do not rely on one completing before another starts."* — this is documented and shipped.

### Scenario-by-scenario yes/no

| Scenario | Supported | How |
|---|---|---|
| Inject system messages at session start ("current date is X, tenant is Y") | **Yes** | `SessionStart` hook returns `{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "..."}}`. See `examples/hooks.py:73-82`. |
| Expand user input (slash commands, attachments, time-stamp) | **Yes** | `UserPromptSubmit` hook returns `additionalContext`. `PreToolUse` `updatedInput` for tool-input expansion. |
| Mutate messages list before each LLM call (e.g. prompt-cache breakpoints, redaction) | **No, not directly** | Hooks do not expose the in-flight messages array. Cache breakpoints and message-array surgery happen inside the CLI subprocess and are not configurable from Python. You can inject *additional* context via `UserPromptSubmit` / `additionalContext`, but you cannot rewrite or redact the existing messages array. |
| Mutate / decorate tool input before dispatch (inject tenantId) | **Yes** | `PreToolUse` → `updatedInput` (`types.py:418`). Also `can_use_tool` → `PermissionResultAllow(updated_input=...)`. Both are exercised at `query.py:415-423`. |
| Mutate / decorate tool result before it returns to the LLM (redact, summarize) | **Yes** | `PostToolUse` → `updatedToolOutput` (`types.py:427-433`). Works for built-in tools (must match the tool's output schema, e.g. `{"stdout":..., "stderr":..., "interrupted":...}` for Bash) and MCP tools. |
| Emit additional tool calls in response to a tool result (Claude TS SDK's `additional_messages`) | **No first-class equivalent.** | `PostToolUse` can inject `additionalContext` (free-text system message) to nudge the model into making another call, but cannot synthetically emit a `tool_use` block on the model's behalf. The closest is `PostToolUse` `additionalContext` instructing the model to run another tool. |

### Architectural diagram — where hooks fire

```
                       ┌─────────────────────────────────────────────┐
                       │           Python (this SDK)                 │
                       │                                             │
                       │  ClaudeSDKClient / query()                  │
                       │       │                                     │
                       │       ▼                                     │
                       │  Query._handle_control_request              │
                       │   ├─ can_use_tool callback                  │
                       │   ├─ hook_callback (PreToolUse, …)          │
                       │   └─ mcp_message (SDK MCP tool dispatch)    │
                       └────────────────┬────────────────────────────┘
                                        │ JSON over stdio
                                        ▼
                       ┌─────────────────────────────────────────────┐
                       │      Claude Code CLI (Node subprocess)      │
                       │                                             │
                       │   user prompt ─┐                            │
                       │                ▼                            │
                       │  ┌─── UserPromptSubmit hook  ───────────┐  │
                       │  │  additionalContext, block            │  │
                       │  └──┬───────────────────────────────────┘  │
                       │     ▼                                       │
                       │   model call (streaming)                    │
                       │     ▼                                       │
                       │   tool_use block detected                   │
                       │     ▼                                       │
                       │  ┌─── PreToolUse hook  ─────────────────┐  │
                       │  │  updatedInput, deny, defer, ask      │  │
                       │  └──┬───────────────────────────────────┘  │
                       │     ▼                                       │
                       │   permission eval                           │
                       │     ▼                                       │
                       │  ┌─── PermissionRequest hook ───────────┐  │
                       │  │  or can_use_tool callback (over RPC) │  │
                       │  └──┬───────────────────────────────────┘  │
                       │     ▼                                       │
                       │   tool dispatch (built-in / MCP / SDK)      │
                       │     ▼                                       │
                       │   result or error                           │
                       │     ▼                                       │
                       │  ┌─── PostToolUse / PostToolUseFailure ──┐ │
                       │  │  updatedToolOutput, additionalContext │ │
                       │  └──┬───────────────────────────────────┘  │
                       │     ▼                                       │
                       │   loop: next model call ──► …               │
                       │     ▼                                       │
                       │  ┌─── PreCompact / Stop / SubagentStop ───┐│
                       │  └────────────────────────────────────────┘│
                       │     ▼                                       │
                       │   ResultMessage  (turn end)                 │
                       └─────────────────────────────────────────────┘
```

Hooks fire as control-protocol RPCs from the CLI → Python; each control request is a separate async task and replies are sent back over stdin.

## 5. API Exposition

### HTTP server?

**No.** Library-only. There is no `app.listen()`, no Flask/FastAPI integration, no built-in SSE endpoint. You BYO HTTP layer (FastAPI, aiohttp, Starlette, whatever) and wrap `query()` or `ClaudeSDKClient` in your handler.

### Transport (between SDK and CLI)

JSON-line over stdin/stdout to a subprocess. Not HTTP — pure pipe IPC. The Python transport is `SubprocessCLITransport` (`src/claude_agent_sdk/_internal/transport/subprocess_cli.py`). Anyone wanting a non-subprocess transport implements the `Transport` protocol (`src/claude_agent_sdk/_internal/transport/__init__.py`) and passes it as `transport=` to `query()` / `ClaudeSDKClient`.

### Wire frame format (illustrative — what flows on stdout from CLI to SDK)

Start of session:
```json
{"type": "system", "subtype": "init", "session_id": "abc-123", "agents": [...], "tools": [...], "model": "claude-sonnet-4-5"}
```

Mid-stream assistant tool call:
```json
{
  "type": "assistant",
  "session_id": "abc-123",
  "uuid": "...",
  "message": {
    "model": "claude-sonnet-4-5",
    "content": [
      {"type": "text", "text": "I'll list the files."},
      {"type": "tool_use", "id": "toolu_01XYZ", "name": "Bash", "input": {"command": "ls"}}
    ],
    "stop_reason": "tool_use",
    "usage": {"input_tokens": 1024, "output_tokens": 42, ...}
  }
}
```

Subsequent tool result (CLI synthesizes a `user` message holding the result):
```json
{
  "type": "user",
  "session_id": "abc-123",
  "message": {
    "content": [
      {"type": "tool_result", "tool_use_id": "toolu_01XYZ", "content": "file1.py\nfile2.py", "is_error": false}
    ]
  }
}
```

Terminal:
```json
{"type": "result", "subtype": "success", "duration_ms": 5421, "duration_api_ms": 4800,
 "is_error": false, "num_turns": 3, "session_id": "abc-123",
 "total_cost_usd": 0.0042, "usage": {...}, "stop_reason": "end_turn"}
```

Control requests (CLI → SDK, requires Python reply):
```json
{"type": "control_request", "request_id": "req_1_a3f9", "request": {
  "subtype": "can_use_tool", "tool_name": "Write", "input": {"file_path": "x.py"},
  "permission_suggestions": [...], "tool_use_id": "toolu_01XYZ"
}}
```

### HITL via API

There is no HTTP/SSE API to send a verdict to — HITL is intra-process. The application has to keep the `ClaudeSDKClient` and its CLI subprocess alive in memory across the user's approval round-trip, and reply by returning from the `can_use_tool` callback. For durable HITL (verdict comes hours later from a different request), the only first-party primitive is the `defer` hook decision: `PreToolUse` returns `permissionDecision: "defer"`, the turn ends with `ResultMessage.deferred_tool_use` set, and a future call must use session resume (`resume=<id>`) with the deferred call applied somehow — but the SDK doesn't ship a "resume with verdict" call, you'd need to re-prompt the model.

### Interrupt via API

`ClaudeSDKClient.interrupt()` (`client.py:313-317`). Sends a control request over the existing stdin pipe; no separate API endpoint. From the wrapping HTTP server, you'd need to map an HTTP DELETE to a call on the same client instance.

### Tool-call ↔ tool-result linking

**Explicit by `tool_use_id`** (`types.py:935-950`):

```python
# src/claude_agent_sdk/types.py:935
@dataclass
class ToolUseBlock:
    id: str            # ← link key
    name: str
    input: dict[str, Any]

@dataclass
class ToolResultBlock:
    tool_use_id: str   # ← matches ToolUseBlock.id
    content: str | list[dict[str, Any]] | None = None
    is_error: bool | None = None
```

Reconstruction from the stream:

1. `AssistantMessage` arrives; iterate `message.content`; for each `ToolUseBlock`, record `(id, name, input)`.
2. Next `UserMessage` (or any subsequent message) arrives; iterate `message.content`; for each `ToolResultBlock`, look up by `tool_use_id` to attach to the matching call.

There is also `UserMessage.parent_tool_use_id` (`types.py:1014-1022`) which marks user messages emitted *from inside a sub-agent's loop* — useful for filtering when reconstructing the main thread.

Sub-agent tasks are also linked via `task_id`:

```python
# src/claude_agent_sdk/types.py:1059
@dataclass
class TaskStartedMessage(SystemMessage):
    task_id: str
    description: str
    uuid: str
    session_id: str
    tool_use_id: str | None = None
    task_type: str | None = None
```

`tool_use_id` on Task messages links to the `Task` tool call that spawned it.

## 6. Sub-agents

### Invocation model

**Both** — sub-agents are first-class but invoked via a tool. The CLI ships a built-in `Task` tool that the parent LLM calls to delegate to a sub-agent. The sub-agent runs its own loop in the CLI subprocess.

### Configuration

Two paths:

1. **Inline programmatic** via `AgentDefinition` (`types.py:82-101`):

```python
# src/claude_agent_sdk/types.py:82
@dataclass
class AgentDefinition:
    description: str
    prompt: str
    tools: list[str] | None = None
    disallowedTools: list[str] | None = None
    model: str | None = None              # alias ("sonnet"/"opus"/"haiku"/"inherit") or full id
    skills: list[str] | None = None
    memory: Literal["user", "project", "local"] | None = None
    mcpServers: list[str | dict[str, Any]] | None = None
    initialPrompt: str | None = None
    maxTurns: int | None = None
    background: bool | None = None
    effort: EffortLevel | int | None = None
    permissionMode: PermissionMode | None = None
```

Set on `ClaudeAgentOptions.agents={"code-reviewer": AgentDefinition(...)}`. Sent via the `initialize` control request (`client.py:217-222`, `query.py:207-208`).

2. **Filesystem markdown** at `.claude/agents/<name>.md` with YAML frontmatter (the conventional Claude Code format, loaded when `setting_sources` includes `"project"` or `"user"`). See `examples/filesystem_agents.py` and `.claude/agents/test-agent.md` in the repo.

### Runtime-generated sub-agents

**Yes** — `AgentDefinition` is a dataclass you can build at request time per-tenant. There is no requirement that the dict be statically declared at boot. The parent LLM cannot itself generate a new `AgentDefinition` mid-run, but the Python harness can decide per-request which agents to register.

### Output to parent

The parent LLM calls the `Task` tool; the sub-agent runs to completion; the result returns as a `ToolResultBlock` (text summary) on the next user message. The parent sees a single result string per sub-agent call — not a stream.

Streaming visibility from the harness is via the `Task*Message` lifecycle (`types.py:1059-1110`):

```python
@dataclass
class TaskStartedMessage(SystemMessage):
    task_id: str
    description: str
    uuid: str
    session_id: str
    tool_use_id: str | None = None
    task_type: str | None = None

@dataclass
class TaskProgressMessage(SystemMessage):
    task_id: str
    description: str
    usage: TaskUsage  # total_tokens, tool_uses, duration_ms
    ...

@dataclass
class TaskNotificationMessage(SystemMessage):
    task_id: str
    status: TaskNotificationStatus  # "completed" | "failed" | "stopped"
    output_file: str
    summary: str
    ...
```

So the harness gets per-task progress/usage telemetry even though the parent LLM gets just the summary string.

### Concurrency model

**Parallel — first-class.** The CLI's `Task` tool supports parallel sub-agent fan-out natively. Sub-agent tool-lifecycle hooks interleave on the control channel; the SDK documents this and provides `_SubagentContextMixin` so hook handlers can attribute concurrent tool calls back to their sub-agent via `agent_id` / `agent_type` (`types.py:289-306`):

```python
class _SubagentContextMixin(TypedDict, total=False):
    """Optional sub-agent attribution fields for tool-lifecycle hooks.
    agent_id: Sub-agent identifier. Present only when the hook fires from
    inside a Task-spawned sub-agent; absent on the main thread.
    ...
    When multiple sub-agents run in parallel their tool-lifecycle hooks
    interleave over the same control channel — this is the only reliable
    way to attribute each one to the correct sub-agent."""
    agent_id: str
    agent_type: str
```

`background: bool` on `AgentDefinition` and `ClaudeSDKClient.stop_task(task_id)` give explicit control over backgrounded sub-agents.

Parallelism is implemented in the CLI; Python only observes the resulting interleaved messages.

### Context isolation

Each sub-agent has its **own transcript** at `<projects_dir>/<project_key>/<session_id>/subagents/agent-<id>.jsonl`. The `SessionStore` adapter sees them as separate `SessionKey` entries with a `subpath` (`types.py:1276-1295`). The parent does not see the sub-agent's internal turns; only the final summary string returned by the `Task` tool. The harness can list/inspect them via `list_subagents()` / `get_subagent_messages()` (exported from `__init__.py:46-52`).

The sub-agent's system prompt is its own — set via `AgentDefinition.prompt`. The parent's context is not inherited (the sub-agent starts fresh with its `prompt` + `initialPrompt`).

## 7. Skills

### First-class?

**Yes, but filesystem-only.** Skills are a native concept in Claude Code (the CLI), and the SDK exposes a single `skills` option to filter them (`types.py:1812-1830`):

```python
# src/claude_agent_sdk/types.py:1812
skills: list[str] | Literal["all"] | None = None
"""Skills to enable for the main session.

- ``None`` (default): no SDK auto-configuration. The CLI's own defaults
  still apply, so this is **not** "skills off" — to suppress every skill
  from the listing, use ``[]``.
- ``"all"``: enable every discovered skill.
- ``list[str]``: enable only the listed skills. Names match the SKILL.md
  ``name`` / directory name, or ``plugin:skill`` for plugin-qualified skills.

This is a **context filter**, not a sandbox: unlisted skills are hidden
from the model's listing and rejected by the Skill tool, but their files
remain on disk and are reachable via Read/Bash. Do not store secrets in
skill files.
"""
```

### Loading mechanism

**Filesystem scan inside the CLI.** The CLI looks at `~/.claude/skills/`, `<cwd>/.claude/skills/`, and `<plugin>/skills/` directories (gated by `setting_sources`). The Python SDK auto-configures `setting_sources=["user", "project"]` and `allowed_tools` to include `Skill` when you set `options.skills` (`subprocess_cli.py:183-219`):

```python
# src/claude_agent_sdk/_internal/transport/subprocess_cli.py:183
def _apply_skills_defaults(self) -> tuple[list[str], list[str] | None]:
    """When ``options.skills`` is ``"all"``, injects the bare ``Skill`` tool;
    when it is a list, injects ``Skill(name)`` for each entry. In either
    case ``setting_sources`` defaults to ``["user", "project"]`` when
    unset so the CLI discovers installed skills without the caller having
    to wire up both options manually. ``None`` is a no-op."""

    if skills == "all":
        if "Skill" not in allowed_tools:
            allowed_tools.append("Skill")
    else:
        for name in skills:
            pattern = f"Skill({name})"
            if pattern not in allowed_tools:
                allowed_tools.append(pattern)
    if setting_sources is None:
        setting_sources = ["user", "project"]
```

The CLI does the actual SKILL.md parsing — it's not exposed in the Python SDK.

### File format

The SDK source does not define the SKILL.md schema (because the CLI owns it). Per Claude Code convention (visible in this repo's own `.claude/commands/`), it's a markdown file with YAML frontmatter: `name`, `description`, optional `triggers`. The actual schema lives in the CLI's Node source, not in this repository.

### Invocation mechanism

**Tool call.** The CLI exposes a built-in `Skill` tool to the model. When the model wants to use skill X it calls `Skill(name="X")`, which (per the CLI's internal logic) loads the SKILL.md body into the conversation as context. So skill invocation is observable from Python as a `ToolUseBlock(name="Skill", input={"name": "..."})`.

### Loading mode

**Lazy.** Per the CLI's design (and confirmed by `ContextUsageResponse.skills` showing "frontmatter breakdown" — `types.py:814-815`), the metadata (name + description from frontmatter) goes in the system prompt; the full body loads on `Skill(name=...)` invocation. This is the same lazy model as in this repo's `update-config` / `slack` / `dm-flux` skills.

### Scoping (global / tenant / user)

**No programmatic per-tenant scoping API.** Skills live on disk under `~/.claude/skills/` or `<cwd>/.claude/skills/`. To scope per-tenant you must either:

- Materialize a per-tenant `.claude/skills/` directory tree, set `options.cwd=<tenant_dir>`, and set `options.setting_sources=["project"]` (excludes the global `~/.claude/`), or
- Use `options.skills=["allowed_skill_1", "allowed_skill_2"]` as a per-request **filter** over the globally-installed skills. But this is acknowledged as "a context filter, not a sandbox" — the files remain accessible to Read/Bash. **Not safe for tenant isolation of sensitive logic.**

For our use case, the practical pattern is: a per-tenant `tenants/<tid>/.claude/skills/` tree, materialized before subprocess spawn, with `cwd=tenants/<tid>`. This adds non-trivial filesystem hygiene work (provisioning, cleanup, atomicity, retention) that other SDKs (e.g. Mastra's `registerSkill(tenantID, ...)`-equivalent) handle in-memory.

## 8. Usage & Cost Monitoring

### Token surfaces

Three levels:

1. **Per LLM call** — `AssistantMessage.usage` (`types.py:1024-1037`) holds the Anthropic API usage block per assistant turn: `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`. Pre-parsed from the wire dict.
2. **Per turn (terminal)** — `ResultMessage.usage` + `ResultMessage.model_usage` (`types.py:1144-1167`). `model_usage` is per-model (when fallback model was used mid-turn).
3. **Sub-agent tasks** — `TaskUsage` (`types.py:1047-1052`) on `TaskProgressMessage` / `TaskNotificationMessage`: `total_tokens`, `tool_uses`, `duration_ms`.

There is no per-session running counter in the Python SDK — you accumulate yourself by summing across `ResultMessage`s.

### Cost (USD)

`ResultMessage.total_cost_usd: float | None` (`types.py:1155`). **The CLI computes this**, not the Python SDK. So we get an authoritative USD figure per turn for free, including across model fallback. **Claude Agent SDK Py is the only stack in our comparison with first-party USD cost on the result object.**

### `max_budget_usd` budget cap

Real and first-party (`types.py:1659-1664`):

```python
# src/claude_agent_sdk/types.py:1659
max_budget_usd: float | None = None
"""Maximum budget in USD for the query.

The query will stop if this budget is exceeded, returning an
``error_max_budget_usd`` result.
"""
```

Wired through to the CLI via `--max-budget-usd` (`subprocess_cli.py:262-263`):

```python
if self._options.max_budget_usd is not None:
    cmd.extend(["--max-budget-usd", str(self._options.max_budget_usd)])
```

The CLI checks after every API call; on overrun the run ends with `ResultMessage.subtype == "error_max_budget_usd"` (see `examples/max_budget_usd.py:72`). Caveat noted in the example: *"The cost may exceed the budget by up to one API call's worth"* — so this is a soft cap, post-call. Adequate for runaway protection, not for hard pre-call budget enforcement.

### Context-window usage

`ClaudeSDKClient.get_context_usage()` (`client.py:506-540`) returns the same data as the CLI's `/context` command — categorized token counts (system prompt, tools, messages, MCP tools, memory files, agents, skills, slash commands), `totalTokens`, `maxTokens`, `percentage`, autocompact threshold. This is fetched via a `get_context_usage` control request and is **live** — call it mid-conversation to see how close you are to the compaction threshold.

### Emission mechanism

- **Events on the message stream** — usage on every `AssistantMessage`, cost on every `ResultMessage`, sub-agent usage on `TaskProgressMessage`. Streamed via the same async iterator.
- **Polled** — `get_context_usage()`, `get_mcp_status()` are explicit RPCs.
- **OTel context auto-propagated to CLI subprocess** (`subprocess_cli.py:441-462`):

```python
# src/claude_agent_sdk/_internal/transport/subprocess_cli.py:441
try:
    from opentelemetry import propagate
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    if "traceparent" in carrier:
        # ...
        for k, v in carrier.items():
            key = k.upper()
            if key not in self._options.env:
                process_env[key] = v
except Exception:
    logger.debug("OTEL trace context injection failed", exc_info=True)
```

So the CLI's spans parent under the caller's distributed trace. The CLI itself emits OTel spans (per Claude Code's own docs); you get an end-to-end trace if your OTel collector receives both Python and CLI spans.

### Canonical "where do I read token counts" code path

```python
async for msg in client.receive_response():
    if isinstance(msg, AssistantMessage) and msg.usage:
        in_tok = msg.usage.get("input_tokens", 0)
        out_tok = msg.usage.get("output_tokens", 0)
        cache_read = msg.usage.get("cache_read_input_tokens", 0)
        cache_create = msg.usage.get("cache_creation_input_tokens", 0)
    elif isinstance(msg, ResultMessage):
        print(f"turn cost ${msg.total_cost_usd}, total tokens {msg.usage}")
```

Per-tenant aggregation: BYO — accumulate `total_cost_usd` keyed by your own tenant id (which you set as the `SessionKey.project_key`).

## Architectural diagram

```
                ┌───────────────────────────────────────────────────────────┐
                │                  Your Python application                  │
                │                                                           │
                │  HTTP server (FastAPI / aiohttp / your choice — BYO)      │
                │       │                                                   │
                │       ▼                                                   │
                │  ClaudeSDKClient or query()                               │
                │       │                                                   │
                │       ▼                                                   │
                │  InternalClient.process_query                             │
                │       │                                                   │
                │       ├── ClaudeAgentOptions  (tools, hooks, agents,      │
                │       │   skills, mcp_servers, can_use_tool, session_     │
                │       │   store, cwd, env, max_budget_usd, …)             │
                │       │                                                   │
                │       └── Query  ── control protocol RPC ──┐              │
                │           │   (hook_callback, can_use_tool,│              │
                │           │    mcp_message handlers in     │              │
                │           │    Python)                     │              │
                │           ▼                                ▼              │
                │   SubprocessCLITransport ──────────► stdin / stdout ──┐   │
                │           │                                            │   │
                │           ├── SessionStore (optional)                  │   │
                │           │   (your async adapter — Postgres, S3, …)  │   │
                │           │                                            │   │
                │           └── In-process SDK MCP servers ──────────────┤   │
                │               (@tool-decorated coroutines that         │   │
                │               run in your process)                     │   │
                │                                                        │   │
                └────────────────────────────────────────────────────────┼───┘
                                                                         │
                                                                         ▼
              ┌──────────────────────────────────────────────────────────────────┐
              │   Claude Code CLI  (Node.js subprocess — bundled in wheel)       │
              │                                                                  │
              │   THE ACTUAL AGENT LOOP RUNS HERE                                │
              │                                                                  │
              │   ┌─────────────────────────────────────────────────────────┐   │
              │   │  System prompt assembly  (preset / file / inline)       │   │
              │   │  Skill discovery + lazy load (filesystem scan)          │   │
              │   │  Sub-agent registry  (AgentDefinition + .claude/agents) │   │
              │   │  CLAUDE.md memory loading                               │   │
              │   │  Slash commands + plugins                               │   │
              │   └─────────────────────────────────────────────────────────┘   │
              │                          │                                       │
              │                          ▼                                       │
              │   ┌─────────────────────────────────────────────────────────┐   │
              │   │  Turn loop:                                             │   │
              │   │    HookFire(UserPromptSubmit, SessionStart, …)          │   │
              │   │    → Anthropic Messages API (streaming)                 │   │
              │   │    → parse content blocks                               │   │
              │   │    → for each tool_use:                                 │   │
              │   │         HookFire(PreToolUse) → updatedInput / deny      │   │
              │   │         permission eval → can_use_tool RPC if "ask"     │   │
              │   │         dispatch tool:                                  │   │
              │   │           - built-in (Read, Write, Bash, Grep, …)       │   │
              │   │           - MCP stdio/SSE/HTTP                          │   │
              │   │           - in-process SDK MCP (RPC back to Python)     │   │
              │   │           - Task → sub-agent loop (parallel)            │   │
              │   │         HookFire(PostToolUse / PostToolUseFailure)      │   │
              │   │    → next turn or stop                                  │   │
              │   │    → emit ResultMessage with total_cost_usd, usage,     │   │
              │   │      stop_reason                                        │   │
              │   └─────────────────────────────────────────────────────────┘   │
              │                          │                                       │
              │                          ▼                                       │
              │   ┌─────────────────────────────────────────────────────────┐   │
              │   │  Persistence:                                           │   │
              │   │   - local JSONL transcript (CLAUDE_CONFIG_DIR)          │   │
              │   │   - transcript_mirror frames → SessionStore via SDK     │   │
              │   └─────────────────────────────────────────────────────────┘   │
              └──────────────────────────────────────────────────────────────────┘
```

## Appendix — Files worth reading first

- **`src/claude_agent_sdk/types.py`** — *single source of truth* for every public type: `ClaudeAgentOptions`, all `*HookInput` / `*HookSpecificOutput`, `Message`, `SessionStore`, `ResultMessage`. Read this first; everything else is a thin layer over it.
- **`src/claude_agent_sdk/_internal/query.py`** — the Python-side run loop: read stdout, route control requests, dispatch hooks / `can_use_tool` / SDK MCP, manage stdin writes. The real "what does the SDK do" file.
- **`src/claude_agent_sdk/_internal/transport/subprocess_cli.py`** — how Python spawns and talks to the bundled CLI binary. The `_build_command` method shows every `ClaudeAgentOptions` field's CLI flag equivalent — useful to understand which knobs the CLI exposes.
- **`src/claude_agent_sdk/_internal/client.py`** — wires `Query` to the chosen `Transport` for one-shot `query()`. Compare with `client.py` (top-level) for the bidirectional `ClaudeSDKClient`.
- **`src/claude_agent_sdk/client.py`** — `ClaudeSDKClient` interactive API (`interrupt`, `set_model`, `set_permission_mode`, `stop_task`, `get_mcp_status`, `get_context_usage`).
- **`src/claude_agent_sdk/_internal/message_parser.py`** — the `match`-on-`type` parser that turns wire dicts into typed dataclasses. Read this to understand what the iterator yields.
- **`src/claude_agent_sdk/_internal/transcript_mirror_batcher.py`** — `SessionStore` mirror batching + retry semantics. Important for understanding durability and at-most-once semantics.
- **`src/claude_agent_sdk/_internal/sessions.py`** + **`session_store.py`** — session listing / `SessionKey` derivation / `InMemorySessionStore` reference implementation.
- **`src/claude_agent_sdk/__init__.py`** — `@tool` decorator + `create_sdk_mcp_server` + everything re-exported. Where to look for "what's in the public API".
- **`examples/hooks.py`** — every hook pattern (block, mutate, defer, continue/stop) in one runnable file.
- **`examples/tool_permission_callback.py`** — canonical `can_use_tool` pattern, including `updated_input` for forcing tool arguments.
- **`examples/session_stores/postgres_session_store.py`** — reference `SessionStore` adapter showing the `SessionKey.project_key` multi-tenant pattern.
- **`examples/max_budget_usd.py`** — the unique `max_budget_usd` feature in action; shows the `error_max_budget_usd` result subtype.
- **`CHANGELOG.md`** — surface area moves fast (0.2.82 ships hooks-concurrency docs, defer hook decision in 0.1.74, `strict_mcp_config` in 0.1.74, `updatedToolOutput` for non-MCP tools in 0.1.74). Worth scanning to date-check features.
