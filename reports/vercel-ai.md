# Vercel AI SDK TS — Benchmark Study

> **Repo**: https://github.com/vercel/ai
> **Commit studied**: `aa5a1e539643c2a7162a141502eee63c665a9544` (branch `main`, version `ai@7.0.0-canary.142`, i.e. "v7-canary" — the matrix called this "v6+")
> **Cloned at**: `benchmarked-stacks/vercel-ai/`
> **Studied on**: 2026-05-16

## TL;DR

- **Strongest fit** for our use case: the v7-canary `ToolLoopAgent` is finally a usable backend abstraction. It bundles `model + instructions + tools + prepareStep + prepareCall + toolApproval + activeTools + experimental_refineToolInput` into a single object, with a `RUNTIME_CONTEXT` generic that flows through the loop without being shown to the LLM. For our multi-tenant agent the combo `runtimeContext` + `prepareStep(activeTools, runtimeContext)` + `experimental_refineToolInput` covers context propagation, per-turn tool filtering, and forced tool-arg overrides — exactly the three things we need most.
- **Biggest gap**: no first-class **sub-agent** primitive, no **skill** loader, and no **durable runtime**. Sub-agents are "make a tool whose `execute` calls another `ToolLoopAgent.generate(...)` and returns the text" — pure BYO. "Skills" (`packages/ai/src/upload-skill/`) only means *uploading a markdown-skill bundle to Anthropic's skills API*; the SDK never loads `SKILL.md` locally and there is no scoping. Resumable streams require an external library (`resumable-stream`) and a custom DB-poll cancel path — see `examples/next/app/api/chat/route.ts:88` and `examples/next/app/api/chat/[id]/stream/route.ts:18`.
- **Most surprising**: the SDK ships *no* HTTP server. `createAgentUIStreamResponse({ agent, uiMessages })` returns a `Response` object — you must mount it on Next.js / Hono / Express / Node-http yourself. The matrix-claimed "first-party frontend primitives" are real (`useChat`, `UIMessageChunk`, `DefaultChatTransport`), but they assume *you* operate both ends of the wire.
- **Most surprising #2 (positive)**: tool-arg streaming (`onInputDelta`, `tool-input-delta` chunks) and tool-arg forcing (`experimental_refineToolInput`) are first-class. Combined with `toolApproval` (per-tool functions returning `'approved'|'denied'|'user-approval'`), the SDK has a more flexible HITL story than LangGraph's `interrupt`.
- **Closest existing-stack analogue**: Mastra (same TS, same `Agent` object, same `useChat`-style hooks, same lack of native durable runtime). Vercel AI SDK is lower-level — Mastra layers workflows, memory, eval and a Playground on top of essentially the same primitives.
- **One-line verdicts**:
  - **Skills**: Not provided — BYO. (`upload-skill` is an Anthropic provider feature, not a stack-level loader.)
  - **Sub-agents**: Not provided — BYO. (Agents-as-tools by hand.)
  - **Multi-tenancy**: Strong. `runtimeContext` + `toolsContext` + `experimental_refineToolInput` cover all three of the audience's hard requirements.
  - **Hooks**: Strong. 7 generation-level callbacks + `prepareStep` + `prepareCall` + 4 tool-level hooks + `LanguageModelMiddleware` (transformParams / wrapGenerate / wrapStream).
  - **API**: Library-only. SSE-over-HTTP `UIMessageChunk` is a well-specified protocol but you mount it yourself. **No `/runs` / `/threads` REST endpoints**.
  - **Observability**: `Telemetry` interface with 12 lifecycle callbacks, per-step `LanguageModelUsage` (incl. cache read/write tokens). **No cost computation in `ai`** — USD cost is only available via AI Gateway's `getSpendReport(...)`.

---

## 1. Message Types & Event Taxonomy

Vercel AI SDK has **three distinct message layers** plus a **fourth event-stream taxonomy** — a structure most TS stacks copy.

**Layer 1 — `ModelMessage`** (`packages/ai/src/prompt/message.ts:23-72`): what the LLM provider sees on the wire. Discriminated union over `system | user | assistant | tool`. Tool messages carry `toolResultPartSchema` and `toolApprovalResponseSchema` parts:

```ts
// packages/ai/src/prompt/message.ts:61
export const toolModelMessageSchema: z.ZodType<ToolModelMessage> = z.object({
  role: z.literal('tool'),
  content: z.array(z.union([toolResultPartSchema, toolApprovalResponseSchema])),
  providerOptions: providerMetadataSchema.optional(),
});

export const modelMessageSchema: z.ZodType<ModelMessage> = z.union([
  systemModelMessageSchema, userModelMessageSchema,
  assistantModelMessageSchema, toolModelMessageSchema,
]);
```

**Layer 2 — `UIMessage<METADATA, DATA_PARTS, TOOLS>`** (`packages/ai/src/ui/ui-messages.ts:44-75`): what the client renders. Each message has `parts: Array<UIMessagePart>`. The part union is rich: `TextUIPart | CustomContentUIPart | ReasoningUIPart | ToolUIPart | DynamicToolUIPart | SourceUrlUIPart | SourceDocumentUIPart | FileUIPart | ReasoningFileUIPart | DataUIPart | StepStartUIPart`. Tool parts carry a **state machine** (`packages/ai/src/ui/ui-messages.ts:291-377`):

```ts
state: 'input-streaming'   // tokens of the JSON args are being streamed
     | 'input-available'   // args fully parsed
     | 'approval-requested'
     | 'approval-responded'
     | 'output-available'
     | 'output-error'
     | 'output-denied'
```

That state field is what makes the "partial rendering of tool calls in flight" UX work without custom plumbing.

**Layer 3 — `ContentPart<TOOLS>`** (`packages/ai/src/generate-text/content-part.ts`): the internal SDK normalized view of one assistant turn's content. Includes `tool-call`, `tool-result`, `tool-error`, `tool-approval-request`, `tool-approval-response`, `reasoning`, `file`, `text`, `source`, `custom`. This is what `StepResult.content` exposes (`packages/ai/src/generate-text/step-result.ts`).

**Layer 4 — Event taxonomy**, split in two sub-layers:

- **`TextStreamPart<TOOLS>`** (`packages/ai/src/generate-text/stream-text-result.ts:537-563`) — what `streamText().fullStream` yields internally. 24 variants:

  ```ts
  // packages/ai/src/generate-text/stream-text-result.ts:537
  export type TextStreamPart<TOOLS extends ToolSet> =
    | TextStreamTextStartPart | TextStreamTextEndPart | TextStreamTextDeltaPart
    | TextStreamReasoningStartPart | TextStreamReasoningEndPart | TextStreamReasoningDeltaPart
    | TextStreamCustomPart
    | TextStreamToolInputStartPart | TextStreamToolInputEndPart | TextStreamToolInputDeltaPart
    | TextStreamSourcePart | TextStreamFilePart | TextStreamReasoningFilePart
    | TextStreamToolCallPart<TOOLS> | TextStreamToolResultPart<TOOLS> | TextStreamToolErrorPart<TOOLS>
    | TextStreamToolOutputDeniedPart<TOOLS>
    | TextStreamToolApprovalRequestPart<TOOLS> | TextStreamToolApprovalResponsePart<TOOLS>
    | TextStreamStartStepPart | TextStreamFinishStepPart
    | TextStreamStartPart | TextStreamFinishPart
    | TextStreamAbortPart | TextStreamErrorPart | TextStreamRawPart;
  ```

- **`UIMessageChunk<METADATA, DATA_TYPES>`** (`packages/ai/src/ui-message-stream/ui-message-chunks.ts:225-396`) — the wire format that crosses the SSE boundary. ~28 chunk types with `strictObject` Zod schemas. This is the **Data Stream Protocol**:

  ```ts
  // packages/ai/src/ui-message-stream/ui-message-chunks.ts:225
  export type UIMessageChunk<METADATA, DATA_TYPES> =
    | { type: 'text-start'; id: string; ... }
    | { type: 'text-delta'; delta: string; id: string; ... }
    | { type: 'text-end'; id: string; ... }
    | { type: 'reasoning-start' | 'reasoning-delta' | 'reasoning-end'; ... }
    | { type: 'tool-input-start'; toolCallId, toolName, dynamic, title, ... }
    | { type: 'tool-input-delta'; toolCallId; inputTextDelta }
    | { type: 'tool-input-available'; toolCallId, toolName, input, ... }
    | { type: 'tool-input-error' | 'tool-output-available' | 'tool-output-error' | 'tool-output-denied' }
    | { type: 'tool-approval-request'; approvalId, toolCallId, isAutomatic? }
    | { type: 'tool-approval-response'; approvalId, approved, reason?, ... }
    | { type: 'source-url' | 'source-document' | 'file' | 'reasoning-file' }
    | { type: 'data-${string}'; id?, data, transient? }
    | { type: 'start-step' | 'finish-step' | 'start' | 'finish' | 'abort' | 'message-metadata' | 'error' }
  ```

The conversion `UIMessage[] → ModelMessage[]` is `convertToModelMessages()` (`packages/ai/src/ui/convert-to-model-messages.ts:46`), and `ModelMessage[] → UIMessageChunk[]` is `streamText().toUIMessageStream({ originalMessages? })`.

The key insight for our audience: **`tool_use` and `tool_result` are explicitly linked by `toolCallId`** (every chunk that touches a tool carries `toolCallId: string`), so reconstructing tool-call state from the stream is positional-free.

## 2. Agent Run Loop

The canonical loop is `generateText` / `streamText` in `packages/ai/src/generate-text/generate-text.ts`. The new `ToolLoopAgent` is a thin wrapper that injects `settings → preparedCall → generateText|streamText` and runs registered callbacks (`packages/ai/src/agent/tool-loop-agent.ts:38-271`):

```ts
// packages/ai/src/agent/tool-loop-agent.ts:38
export class ToolLoopAgent<CALL_OPTIONS, TOOLS, RUNTIME_CONTEXT, OUTPUT>
  implements Agent<CALL_OPTIONS, TOOLS, RUNTIME_CONTEXT, OUTPUT> {
  // ...
  async generate(params: AgentCallParameters<...>):
    Promise<GenerateTextResult<TOOLS, RUNTIME_CONTEXT, OUTPUT>>;
  async stream(params: AgentStreamParameters<...>):
    Promise<StreamTextResult<TOOLS, RUNTIME_CONTEXT, OUTPUT>>;
}
```

**The actual loop** (`packages/ai/src/generate-text/generate-text.ts:653-1163`) is a `do { ... } while(...)`:

```ts
// packages/ai/src/generate-text/generate-text.ts:653
do {
  const prepareStepResult = await prepareStep?.({
    model, steps, stepNumber: steps.length,
    instructions, initialInstructions,
    messages: stepInputMessages, initialMessages, responseMessages,
    runtimeContext, toolsContext, experimental_sandbox,
  });
  // 1. resolve per-step overrides for model / instructions / messages / tools / toolChoice / activeTools / runtimeContext / toolsContext
  // 2. convertToLanguageModelPrompt(...)
  // 3. notify onStepStart + onLanguageModelCallStart
  // 4. await stepModel.doGenerate(...)            // ← LLM call
  // 5. notify onLanguageModelCallEnd
  // 6. parseToolCall(...) for each tool-call part
  // 7. resolveToolApproval(...) → 'user-approval' | 'approved' | 'denied'
  // 8. executeTools(...) for all approved client tool calls
  //    → triggers onToolExecutionStart / onToolExecutionEnd per tool
  // 9. build StepResult, push to steps[], notify onStepFinish
} while (
  ((clientToolCalls.length > 0 &&
    clientToolOutputs.length + deniedToolApprovalResponses.length === clientToolCalls.length)
    || pendingDeferredToolCalls.size > 0)
  && !(await isStopConditionMet({ stopConditions, steps }))
);
```

**Turn boundary**: a "step" = one LLM call + zero-or-more parallel tool executions. `stopWhen` defaults to `isStepCount(20)` in `ToolLoopAgent` (`packages/ai/src/agent/tool-loop-agent.ts:121`) and `isStepCount(1)` in raw `generateText` (`packages/ai/src/generate-text/generate-text.ts:227`). Other stop conditions (`hasToolCall(name)`, custom) live in `packages/ai/src/generate-text/stop-condition.ts`.

**Sessions / threads** — *not modeled in the loop*. The SDK has no `Session`, no `Thread`, no built-in store. State lives in:
- `UIMessage[]` on the client (in-memory in `Chat` state, persisted by you).
- `StepResult[]` returned in the `GenerateTextResult`.

The example `examples/next/app/api/chat/route.ts:21` reads from a user-written `readChat(id)` / `saveChat({ id, messages })`. There is no `ai`-provided store interface.

**Persistence timing**: not built in. The closest the SDK provides:
- `onStepFinish` (`packages/ai/src/generate-text/generate-text.ts:1146`) fires after each step's tool-execution completes. The user is expected to persist here.
- For UI-message streams, `handleUIMessageStreamFinish` (`packages/ai/src/ui-message-stream/handle-ui-message-stream-finish.ts:121-142`) calls a user-supplied `onStepFinish({ responseMessage, messages })` per `finish-step` chunk and `onFinish` once at the end.

**Event emission**: callback-based `notify({ event, callbacks })` (`packages/ai/src/util/notify.ts`) called at lifecycle points inside the loop. The `streamText` variant additionally exposes a `fullStream: AsyncIterableStream<TextStreamPart<TOOLS>>` (`packages/ai/src/generate-text/stream-text-result.ts:309`). So both push (callbacks) and pull (async iterator) consumption work.

**HITL pause/resume**: the loop *blocks* on a tool approval automatically — but there is no `pause()` / `resume(verdict)` API. The pattern is:

1. `resolveToolApproval(...)` (`packages/ai/src/generate-text/generate-text.ts:896`) returns `'user-approval'` for one or more tool calls.
2. Those calls are added to `blockedToolCallIds`; their `executeTools` is skipped (`packages/ai/src/generate-text/generate-text.ts:993`).
3. The loop exits because `clientToolOutputs.length + deniedToolApprovalResponses.length === clientToolCalls.length` fails (some calls are blocked, no outputs for them).
4. `GenerateTextResult` is returned with `tool-approval-request` parts in its last step.
5. Caller appends a `{ role: 'tool', content: [{ type: 'tool-approval-response', approvalId, approved, reason }] }` message and **calls `agent.generate({ messages })` again** (see `examples/ai-functions/src/agent/openai/generate-tool-approval.ts:42-101`).

On re-entry, the loop pre-processes approvals at `generate-text.ts:544` (`collectToolApprovals` + execute approved + record execution-denied for denied) *before* the LLM is called again. So the protocol is "stateless re-run with verdicts in the message history" — clean, but you must own the persistence yourself.

**Interrupt / cancel**: standard `AbortSignal` plumbing.

```ts
// packages/ai/src/generate-text/generate-text.ts:467
const totalTimeoutMs = getTotalTimeoutMs(timeout);
const stepTimeoutMs = getStepTimeoutMs(timeout);
const stepAbortController = stepTimeoutMs != null ? new AbortController() : undefined;
const mergedAbortSignal = mergeAbortSignals(abortSignal, totalTimeoutMs, stepAbortController?.signal);
```

`timeout` accepts `{ totalMs, stepMs, chunkMs, toolMs, tools: {…} }` per `packages/ai/src/prompt/request-options.ts`. Cancel propagates to the `doGenerate` / `doStream` provider call. For the persisted use case, `examples/next/app/api/chat/[id]/stream/route.ts:30-42` uses a DELETE endpoint that writes a `canceledAt` field — and the running route polls it via `onChunk: throttle(async () => { ... if (canceledAt) userStopSignal.abort(); }, 1000)` (`examples/next/app/api/chat/route.ts:66-72`). Genuinely out-of-band cancel requires you to wire that yourself.

## 3. Multi-tenancy & Arbitrary Context

This area is **surprisingly well-engineered for v7**. There are *three* harness-provided context buckets that the LLM never sees:

- **`runtimeContext: RUNTIME_CONTEXT`** — agent-wide, per-call.
- **`toolsContext: InferToolSetContext<TOOLS>`** — per-tool-name typed bag, validated against the tool's `contextSchema`.
- **`prepareStep`** — per-step override of either, plus tools / model / messages.

### Full run-loop input struct

`ToolLoopAgentSettings` (`packages/ai/src/agent/tool-loop-agent-settings.ts:42-306`) is the constructor; the per-call `AgentCallParameters` (`packages/ai/src/agent/agent.ts:27-113`) layers on `prompt | messages`, callbacks, `abortSignal`, `timeout`, sandbox. Fields beyond `messages`:

```ts
// packages/ai/src/agent/tool-loop-agent-settings.ts:42
export type ToolLoopAgentSettings<CALL_OPTIONS, TOOLS, RUNTIME_CONTEXT, OUTPUT> =
  LanguageModelCallOptions & Omit<RequestOptions<TOOLS>, 'abortSignal'> & ToolsContextParameter<TOOLS> & {
    id?: string;
    instructions?: Instructions;
    model: LanguageModel;
    toolChoice?: ToolChoice<NoInfer<TOOLS>>;
    stopWhen?: Arrayable<StopCondition<NoInfer<TOOLS>, RUNTIME_CONTEXT>>;
    telemetry?: TelemetryOptions<RUNTIME_CONTEXT, NoInfer<TOOLS>>;
    activeTools?: ActiveTools<NoInfer<TOOLS>>;
    output?: OUTPUT;
    runtimeContext?: RUNTIME_CONTEXT;
    toolApproval?: ToolApprovalConfiguration<NoInfer<TOOLS>, RUNTIME_CONTEXT>;
    prepareStep?: PrepareStepFunction<NoInfer<TOOLS>, RUNTIME_CONTEXT>;
    experimental_repairToolCall?: ToolCallRepairFunction<NoInfer<TOOLS>>;
    experimental_refineToolInput?: ToolInputRefinement<NoInfer<TOOLS>>;
    experimental_onStart, experimental_onStepStart,
    onToolExecutionStart, onToolExecutionEnd,
    onStepFinish, onFinish, ...
    providerOptions?: ProviderOptions;
    callOptionsSchema?: FlexibleSchema<CALL_OPTIONS>;
    prepareCall?: (options: AgentCallParameters<...> & { toolsContext }) => MaybePromiseLike<...>;
  };
```

### Context → tool invocation

Every tool's `execute(input, options)` receives a `ToolExecutionOptions<CONTEXT>` (`packages/provider-utils/src/types/tool-execute-function.ts:8-44`):

```ts
// packages/provider-utils/src/types/tool-execute-function.ts:8
export interface ToolExecutionOptions<CONTEXT> {
  toolCallId: string;
  messages: ModelMessage[];   // history that produced the call (no system, no this turn's assistant)
  abortSignal?: AbortSignal;
  context: CONTEXT;           // ← validated against tool.contextSchema
  experimental_sandbox?: Sandbox;
}

export type ToolExecuteFunction<INPUT, OUTPUT, CONTEXT> = (
  input: INPUT,
  options: ToolExecutionOptions<CONTEXT>,
) => AsyncIterable<OUTPUT> | PromiseLike<OUTPUT> | OUTPUT;
```

The `context` is *only* the per-tool slice. Note the loop hands `runtimeContext` (the agent-wide bag) to `prepareStep`, `experimental_onStart`, telemetry, callbacks — but **not** to the tool's `execute`. If a tool needs tenant info, you put it in the tool's `contextSchema`-validated `toolsContext[toolName]` slot, *or* close over it in your tool factory (which is what most examples do).

### Forcing tool arguments from the harness

**Yes — first-class** via `experimental_refineToolInput` (`packages/ai/src/generate-text/tool-input-refinement.ts:14-19`):

```ts
// packages/ai/src/generate-text/tool-input-refinement.ts:14
export type ToolInputRefinement<TOOLS extends ToolSet> = {
  [NAME in keyof TOOLS]?: (
    input: InferToolInput<TOOLS[NAME]>,
  ) => MaybePromiseLike<InferToolInput<TOOLS[NAME]>>;
};
```

Per-tool function that receives the LLM-generated input and returns a corrected one with the **same shape**. Applied inside `parseToolCall` before the call is dispatched (`packages/ai/src/generate-text/generate-text.ts:807-815`), so the refined input is what tools, callbacks, and telemetry all see. Example:

```ts
// examples/ai-functions/src/agent/openai/generate-refine-tool-input.ts:22
experimental_refineToolInput: {
  weather: input => ({ city: input.city.trim().toLowerCase() }),
},
```

**Caveat**: must return the same JSON shape (no narrowing the type). For a hard "always pass `tenantId=<X>`" pattern you'd typically also put `tenantId` in the tool's `toolsContext[name]` and have `execute` ignore the LLM-supplied value entirely. **This is the most aggressive "harness forces tool args" mechanism among the five stacks.**

### Filtering visible tools

**Yes** — at three layers, all coexisting:

1. **`activeTools: ActiveTools<TOOLS>`** at agent-construction (`packages/ai/src/agent/tool-loop-agent-settings.ts:96`) limits which tools the LLM sees while preserving the `TOOLS` type for result typings.
2. **`prepareStep({ ..., runtimeContext, toolsContext }) → { activeTools?, tools? }`** at per-step (`packages/ai/src/generate-text/prepare-step.ts:99-172`). You can flip `activeTools` between steps based on whatever the runtime context tells you (e.g. "after step 2, drop the search tool"). The override applies to `filterActiveTools` (`packages/ai/src/generate-text/filter-active-tools.ts:21-38`).
3. **`prepareCall({ options, ...rest }) → { tools? }`** at per-call (`packages/ai/src/agent/tool-loop-agent-settings.ts:230-305`). Lets a single `ToolLoopAgent` template generate different tool sets per request based on validated `CALL_OPTIONS`.

### Resource scoping primitives

- **Per-tool context schema**: `tool({ contextSchema, execute })` declares what context the tool needs (`packages/provider-utils/src/types/tool.ts:95-99`). At runtime `validateToolContext` validates and rejects mismatches (`packages/ai/src/generate-text/validate-tool-context.ts`).
- **Per-call `runtimeContext` typing**: `ToolLoopAgent<CALL_OPTIONS, TOOLS, RUNTIME_CONTEXT, OUTPUT>` constrains both at compile time.
- **No global / tenant / user scope on tools or skills directly.** You build that yourself by templating the agent (one `ToolLoopAgent` per tenant) or by using `prepareStep` / `prepareCall` to filter `activeTools` based on `runtimeContext.tenantId`.

## 4. Hook Capabilities

Vercel AI SDK exposes more hooks than any other stack we benchmarked — 7 generation-level + 4 tool-level + 1 LLM-call-level pair + the 3-method `LanguageModelMiddleware`. They are *not* called "hooks"; they are callbacks on `generateText` / `streamText` / `ToolLoopAgent`.

### Generation-level callbacks

From `packages/ai/src/generate-text/generate-text-events.ts:198-244`:

| Callback                          | When                                                                | What it can do                                                       |
| --------------------------------- | ------------------------------------------------------------------- | -------------------------------------------------------------------- |
| `experimental_onStart`            | Once, before any LLM call (after prompt is standardized)            | Read-only — log, init state                                          |
| `experimental_onStepStart`        | Before each step's LLM call (after `prepareStep` has resolved)      | Read-only — log, span-start                                          |
| `experimental_onLanguageModelCallStart` | Immediately before `model.doGenerate / doStream` is called      | Read-only — finer than `onStepStart` (no tool-exec time)             |
| `experimental_onLanguageModelCallEnd`   | After provider response is parsed (before client tool exec)     | Read-only — capture raw model output                                 |
| `onToolExecutionStart`            | Before each tool's `execute` is invoked                             | Read-only                                                            |
| `onToolExecutionEnd`              | After each tool's `execute` completes / errors                      | Read-only — **cannot inject additional tool calls**                  |
| `onStepFinish`                    | After step's tool executions complete                               | Read-only (StepResult is frozen)                                     |
| `onFinish`                        | After loop exits                                                    | Read-only — typical persistence point                                |

`onToolExecutionEnd` returns `void | PromiseLike<void>` — confirmed at `packages/ai/src/generate-text/tool-execution-events.ts:160`. So **no equivalent to Claude Agent SDK's `additional_messages` from `PostToolUse`**. To add a follow-up tool call you have to wait for the next loop iteration and let the LLM decide.

### Transformation hooks (these *can* mutate)

| Hook                                                | When                              | What it can do                                                                                                  |
| --------------------------------------------------- | --------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| `prepareCall(opts) → opts'`                         | Once, before the run-loop starts (only in `ToolLoopAgent`) | Override model, tools, instructions, stopWhen, telemetry, activeTools, toolApproval, providerOptions, include, runtimeContext, _internal — basically anything except `callOptionsSchema` and the prompt/messages |
| `prepareStep(opts) → { model?, toolChoice?, activeTools?, instructions?, messages?, toolsContext?, runtimeContext?, providerOptions?, experimental_sandbox? }` | Before each step's LLM call | Per-step override of nearly everything. The `messages` override **carries forward**.                            |
| `experimental_repairToolCall(toolCall, error) → fixed` | When a tool call fails to parse | Repair invalid JSON / hallucinated args                                                                         |
| `experimental_refineToolInput[toolName]: (input) → input'` | After tool call is parsed, before dispatch | Mutate or fully override tool args (must keep shape)                                                            |
| `LanguageModelMiddleware.transformParams({ params, type, model }) → params'` | Before doGenerate/doStream      | Mutate full provider call options (prompt, tools, headers, etc.)                                                |
| `LanguageModelMiddleware.wrapGenerate({ doGenerate, doStream, params, model })` | Around doGenerate                | Implement retry, cache, simulate-stream, redact, fallback, fan-out                                              |
| `LanguageModelMiddleware.wrapStream({ doGenerate, doStream, params, model })`   | Around doStream                  | Same, for streaming                                                                                             |

`LanguageModelMiddleware` lives at `packages/provider/src/language-model-middleware/v4/language-model-v4-middleware.ts:11-84` and is composed via `wrapLanguageModel({ model, middleware: [m1, m2, ...] })` (`packages/ai/src/middleware/wrap-language-model.ts:25-42`).

### Scenario check

- **Inject system messages at session start (e.g. "current date is X, tenant is Y")?** ✅ Yes — multiple ways:
  - Static: pass `instructions: 'You are X. Current date is ' + new Date().toISOString()` to `ToolLoopAgent`.
  - Dynamic per call: `prepareCall({ ...rest }) => ({ ...rest, instructions: '...' + rest.runtimeContext.tenantName })`.
  - Dynamic per step: `prepareStep({ runtimeContext, ... }) => ({ instructions: '...' })`.
- **Expand the user input (slash commands, time-stamp, attachments)?** ✅ Yes — `prepareCall` lets you rewrite the prompt; for messages you can rewrite via `prepareStep({ ..., messages: [...rewrittenMessages] })`. Note `messages` override carries forward, so do it once.
- **Mutate the messages list before each LLM call (e.g. prompt-cache breakpoints, redaction)?** ✅ Yes — `prepareStep` returns a `messages` override, or `LanguageModelMiddleware.transformParams` mutates the provider-level prompt array.
- **Mutate / decorate tool input before dispatch (e.g. inject tenantId server-side)?** ✅ Yes — `experimental_refineToolInput[name]`.
- **Mutate / decorate tool result before it returns to the LLM (e.g. redact, summarize)?** ⚠️ **Partially** — `onToolExecutionEnd` is read-only. The only way is `tool({ toModelOutput: ({ input, output }) => ToolResultOutput })` (`packages/provider-utils/src/types/tool.ts:148`), which is per-tool and runs inside the tool definition, not as a global hook. There is no global "post-tool-result-redactor" hook.
- **Emit additional tool calls in response to a tool result (Claude Agent SDK's `PostToolUse` `additional_messages`)?** ❌ **No.** Confirmed — `onToolExecutionEnd` returns `void | PromiseLike<void>`. The only way is to write a *tool* whose `execute` itself runs more work and returns the combined result. There is no harness-driven "after tool X, also queue tool Y" mechanism.

### Where hooks fire (ASCII diagram)

```
ToolLoopAgent.generate(params)
  │
  ├─ prepareCall(opts)                                  ← [PRE-LOOP HOOK]
  │
  ▼
generateText(...)
  │
  ├─ standardizePrompt(initialPrompt)
  ├─ collectToolApprovals(messages)                     ← (re-entry path: execute pre-approved tools)
  ├─ notify experimental_onStart                        ← [HOOK 1]
  │
  └─ do {
     │
     ├─ prepareStep({ messages, runtimeContext, ... })  ← [PER-STEP HOOK]
     │   → { model?, instructions?, messages?, activeTools?, toolChoice?, runtimeContext?, ... }
     │
     ├─ filterActiveTools / prepareTools
     ├─ notify experimental_onStepStart                 ← [HOOK 2]
     ├─ notify experimental_onLanguageModelCallStart    ← [HOOK 3]
     │
     ├─ LanguageModelMiddleware.transformParams         ← [PROVIDER-LEVEL HOOK]
     ├─ LanguageModelMiddleware.wrapGenerate/wrapStream ← [PROVIDER-LEVEL HOOK]
     │   → model.doGenerate / model.doStream
     │
     ├─ parseToolCall(...)                              (calls experimental_repairToolCall if needed)
     │   └─ experimental_refineToolInput[name]          ← [PER-TOOL-CALL HOOK]
     │
     ├─ notify experimental_onLanguageModelCallEnd      ← [HOOK 4]
     │
     ├─ tool.onInputAvailable per call                  ← [PER-TOOL CALLBACK]
     ├─ resolveToolApproval(...)
     │   → 'user-approval' → skip exec, surface request
     │   → 'denied' → skip exec, surface response
     │
     ├─ for each approved tool call (parallel):
     │   ├─ notify onToolExecutionStart                 ← [HOOK 5]
     │   ├─ executeTool(...)
     │   │   ├─ tool.onInputStart, tool.onInputDelta    ← [PER-TOOL CALLBACK, stream only]
     │   │   └─ tool.execute(input, { context, abortSignal, ... })
     │   ├─ tool.toModelOutput?(output)                 ← [PER-TOOL CALLBACK]
     │   └─ notify onToolExecutionEnd                   ← [HOOK 6]
     │
     ├─ build StepResult, push to steps[]
     └─ notify onStepFinish                             ← [HOOK 7]
     }
     while (clientToolCalls remaining && !isStopConditionMet)
     │
     └─ notify onFinish                                 ← [HOOK 8]
```

## 5. API Exposition

**Library-only. No HTTP server is shipped.** You build the endpoint in your framework of choice and the SDK gives you helpers to return a `Response` or pipe to a Node `ServerResponse`.

```ts
// examples/next-agent/app/api/chat/route.ts:1
import { weatherAgent } from '@/agent/weather-agent';
import { createAgentUIStreamResponse } from 'ai';

export async function POST(request: Request) {
  const { messages } = await request.json();
  return createAgentUIStreamResponse({ agent: weatherAgent, uiMessages: messages });
}
```

```ts
// examples/express/src/server.ts:36
app.post('/chat', async (request, response) => {
  pipeAgentUIStreamToResponse({
    agent: openaiWebSearchAgent,
    uiMessages: request.body.messages,
    response,
  });
});
```

Three helpers exist:

- `createAgentUIStreamResponse({ agent, uiMessages, options, abortSignal, timeout, ... })` → `Promise<Response>` (`packages/ai/src/agent/create-agent-ui-stream-response.ts:36`)
- `pipeAgentUIStreamToResponse({ agent, uiMessages, response, ... })` → `Promise<void>` (Node `http.ServerResponse`) (`packages/ai/src/agent/pipe-agent-ui-stream-to-response.ts:36`)
- `createAgentUIStream({ ... })` → `Promise<AsyncIterableStream<UIMessageChunk>>` — for embedding into a custom transport (`packages/ai/src/agent/create-agent-ui-stream.ts:38`)

### Transport: SSE

`createUIMessageStreamResponse` (`packages/ai/src/ui-message-stream/create-ui-message-stream-response.ts:19`) wraps a `ReadableStream<UIMessageChunk>` with `JsonToSseTransformStream` (`packages/ai/src/ui-message-stream/json-to-sse-transform-stream.ts:6`):

```ts
// packages/ai/src/ui-message-stream/json-to-sse-transform-stream.ts:6
export class JsonToSseTransformStream extends TransformStream<unknown, string> {
  constructor() {
    super({
      transform(part, controller) {
        controller.enqueue(`data: ${JSON.stringify(part)}\n\n`);
      },
      flush(controller) {
        controller.enqueue('data: [DONE]\n\n');
      },
    });
  }
}
```

Response headers (`packages/ai/src/ui-message-stream/ui-message-stream-headers.ts`):
- `Content-Type: text/event-stream`
- `Cache-Control: no-cache`
- `Connection: keep-alive`
- `x-vercel-ai-ui-message-stream: v2`

### Request shape

`HttpChatTransport` (the default frontend transport) `POST`s JSON (`packages/ai/src/ui/http-chat-transport.ts:145-213`):

```ts
// packages/ai/src/ui/http-chat-transport.ts:178
body: {
  ...resolvedBody,
  ...options.body,
  id: options.chatId,
  messages: options.messages,                  // UIMessage[]
  trigger: 'submit-message' | 'regenerate-message',
  messageId: options.messageId,
}
```

`prepareSendMessagesRequest` (`packages/ai/src/ui/http-chat-transport.ts:11`) lets the client *fully rewrite* this body before send. Audience-relevant: this is where you'd inject a `tenantId` / scoped JWT, or trim `messages` down to just the last (`examples/next/app/chat/[chatId]/chat.tsx:27-50`).

### Event frame format

Example frames (output of `JsonToSseTransformStream`):

```
data: {"type":"start","messageId":"msg_xyz"}\n\n

data: {"type":"start-step"}\n\n

data: {"type":"tool-input-start","toolCallId":"call_001","toolName":"weather","dynamic":false}\n\n

data: {"type":"tool-input-delta","toolCallId":"call_001","inputTextDelta":"{\"city\":\""}\n\n

data: {"type":"tool-input-delta","toolCallId":"call_001","inputTextDelta":"Paris\"}"}\n\n

data: {"type":"tool-input-available","toolCallId":"call_001","toolName":"weather","input":{"city":"Paris"}}\n\n

data: {"type":"tool-output-available","toolCallId":"call_001","output":{"city":"Paris","weather":"sunny"}}\n\n

data: {"type":"text-start","id":"txt_1"}\n\n
data: {"type":"text-delta","id":"txt_1","delta":"It is sunny in Paris."}\n\n
data: {"type":"text-end","id":"txt_1"}\n\n

data: {"type":"finish-step"}\n\n
data: {"type":"finish","finishReason":"stop"}\n\n

data: [DONE]\n\n
```

### HITL via API

The protocol is "client receives `tool-approval-request`, re-posts an updated messages list".

- The client gets a `tool-approval-request` UIMessage part (state `'approval-requested'`).
- The client (or user) calls `chat.addToolApprovalResponse({ id, approved, reason })` (`packages/ai/src/ui/chat.ts:477`). This mutates the in-memory message to state `'approval-responded'`.
- If `sendAutomaticallyWhen({ messages }) → true` is configured, the chat re-POSTs `messages` to `/api/chat`. The server's next `agent.generate({ messages })` call sees the approval responses inside the tool messages and the loop resumes (`packages/ai/src/generate-text/generate-text.ts:544`).

**There is no dedicated `/approve` endpoint.** Same `POST /api/chat` carries everything.

### Interrupt via API

Two patterns, both BYO:

- **Single-server**: client calls `chat.stop()` (`packages/ai/src/ui/chat.ts:586`), which calls `this.activeResponse?.abortController.abort()` — aborts the local fetch. The server's `request.signal` (Next.js `Request`) is then aborted, propagating to `streamText({ abortSignal })`.
- **Multi-server / load-balanced** (`examples/next/app/api/chat/[id]/stream/route.ts:30`): client does `DELETE /api/chat/:id/stream`, the route writes `canceledAt: Date.now()` to your DB, and the running route polls `readChat(id).canceledAt` via `onChunk` throttled at 1s (`examples/next/app/api/chat/route.ts:66-72`) to abort its own signal.

### Reconstructing tool-call state from the stream

**Explicitly linked via `toolCallId`** in every relevant chunk:

```ts
// packages/ai/src/ui-message-stream/ui-message-chunks.ts:46
| { type: 'tool-input-start';      toolCallId, toolName, ... }
| { type: 'tool-input-delta';      toolCallId, inputTextDelta }
| { type: 'tool-input-available';  toolCallId, toolName, input, ... }
| { type: 'tool-input-error';      toolCallId, toolName, input, errorText }
| { type: 'tool-approval-request'; approvalId, toolCallId, isAutomatic? }
| { type: 'tool-approval-response';approvalId, approved, reason?, ... }
| { type: 'tool-output-available'; toolCallId, output, preliminary? }
| { type: 'tool-output-error';     toolCallId, errorText, ... }
| { type: 'tool-output-denied';    toolCallId }
```

`tool-approval-response` correlates by `approvalId`; everything else by `toolCallId`. Positional reconstruction is never required.

## 6. Sub-agents

**Not provided — BYO.** No `subAgent`, `handoff`, `delegate`, `Crew`, `Swarm`, or any sub-agent primitive exists in `packages/ai/src/`.

The pattern that the SDK's own examples + docs implicitly endorse is **"agents-as-tools"**: instantiate a child `ToolLoopAgent`, wrap it in a `tool({ ... execute })`:

```ts
import { tool, ToolLoopAgent } from 'ai';

const researcher = new ToolLoopAgent({ model: openai('gpt-4o-mini'), tools: { /* ... */ } });

const orchestrator = new ToolLoopAgent({
  model: openai('gpt-5'),
  tools: {
    research: tool({
      description: 'Delegate a research task to a sub-agent.',
      inputSchema: z.object({ task: z.string() }),
      execute: async ({ task }, { context, abortSignal }) => {
        const result = await researcher.generate({ prompt: task, abortSignal });
        return result.text;
      },
    }),
  },
});
```

The audience should treat sub-agents as **a pattern you build yourself** — there is no SDK code path that recognizes a tool as "an agent" for telemetry, streaming, fan-out, isolation, or cost attribution.

- **How configured**: by you, at boot or per-call (since `ToolLoopAgent` is just a class).
- **Parent generates sub-agent on the fly?** No native support. You can write a meta-tool whose `execute` body itself instantiates a `ToolLoopAgent` with `instructions` / `tools` from its input, but the SDK has no opinion on this.
- **Output to parent**: whatever the tool returns. Streaming sub-agent results back through the parent's stream requires `createUIMessageStream({ execute: ({ writer }) => writer.merge(subAgent.stream(...).toUIMessageStream({ sendStart: false })) })` (`examples/express/src/server.ts:46`).
- **Concurrency**: serial if you `await`. Parallel if you `Promise.all`. Inside the parent loop, multiple tool calls in a single step are already parallel (`packages/ai/src/generate-text/generate-text.ts:1284`).
- **Context isolation**: each child `ToolLoopAgent.generate({ messages })` starts with whatever messages you give it. No automatic parent-context inheritance.

## 7. Skills

**Not provided as a stack-level concept.** The `packages/ai/src/upload-skill/` package is a thin client around **Anthropic's `/v1/skills` HTTP endpoint** — it uploads a bundle of files (markdown + scripts) so Anthropic can attach skills to a model call.

```ts
// packages/ai/src/upload-skill/upload-skill.ts:17
export async function uploadSkill({
  api,                                  // SkillsV4 | ProviderV4 (must support .skills())
  files,                                // [{ path, data }]
  displayTitle,
  providerOptions,
}): Promise<UploadSkillResult> {
  const skillsApi: SkillsV4 = 'uploadSkill' in api ? api : api.skills();
  // ... normalize files (Uint8Array | string | { type: 'data', data }) ...
  return await skillsApi.uploadSkill({ files: normalizedFiles, displayTitle, providerOptions });
}
```

The Anthropic implementation (`packages/anthropic/src/skills/anthropic-skills.ts:67-131`) POSTs `multipart/form-data` with `anthropic-beta: skills-2025-10-02` to `/v1/skills` and returns a `providerReference: { anthropic: <skillId> }` you store and pass back to model calls. The SDK never reads `SKILL.md` from a local filesystem, has no concept of "loading skill metadata into the system prompt", and has no scoping (tenant / user / global).

Among the five stacks compared, **only Claude Agent SDK Py treats skills as a first-class loaded concept**. Mastra and LangGraph also don't have skills. Vercel AI SDK matches their "no skills" status, plus adds the Anthropic-specific upload helper that is *not* a skill loader.

- **Skill = first-class?** No. (Anthropic-provider upload only.)
- **Loaded from filesystem?** No.
- **Format?** Anthropic API expects markdown + optional script files in a multipart upload; the SDK doesn't define `SKILL.md` frontmatter.
- **Invocation mechanism?** N/A — it's provider-side.
- **Loading mode?** N/A.
- **Scoped (global / tenant / user)?** N/A — you'd track `skillId` ↔ tenant mapping in your own DB.

## 8. Usage & Cost Monitoring

### Where token counts surface

Per-step on every `StepResult`:

```ts
// packages/ai/src/types/usage.ts:10
export type LanguageModelUsage = {
  inputTokens: number | undefined;
  inputTokenDetails: {
    noCacheTokens: number | undefined;
    cacheReadTokens: number | undefined;
    cacheWriteTokens: number | undefined;
  };
  outputTokens: number | undefined;
  outputTokenDetails: {
    textTokens: number | undefined;
    reasoningTokens: number | undefined;
  };
  totalTokens: number | undefined;
  raw?: JSONObject;     // provider-shape passthrough
};
```

Sub-token detail (cache read/write, reasoning) is unusually thorough — better-suited to prompt-cache cost analysis than most stacks.

### Aggregation levels

- **Per LLM call**: `currentModelResponse.usage` is parsed inside the loop (`packages/ai/src/generate-text/generate-text.ts:798`).
- **Per step**: `StepResult.usage` (`packages/ai/src/generate-text/step-result.ts`).
- **Per run**: `GenerateTextResult.totalUsage` and `GenerateTextResult.usage` (`packages/ai/src/generate-text/generate-text.ts:1167-1185, 1414-1416`) computed via `addLanguageModelUsage` reduce over `steps`.
- **Per session / tenant**: not built in. You aggregate yourself via `onFinish` callback or telemetry.

### Mechanism

Three parallel surfaces, all driven by the same internal `notify(...)`:

1. **Result objects**: `result.usage`, `step.usage`.
2. **Callbacks**: `onStepFinish(step => ...)`, `onFinish({ totalUsage, ... } => ...)`, `experimental_onLanguageModelCallEnd({ usage } => ...)`.
3. **`Telemetry` integration**: registered globally or per call (`packages/ai/src/telemetry/telemetry.ts:80-218`). Twelve lifecycle callbacks (`onStart`, `onStepStart`, `onLanguageModelCallStart`, `onLanguageModelCallEnd`, `onToolExecutionStart`, `onToolExecutionEnd`, `onStepFinish`, `onObjectStepStart/Finish`, `onEmbedStart/End`, `onRerankStart/End`, `onEnd`, `onError`) + `executeTool` wrapping for nested-span propagation:

   ```ts
   // packages/ai/src/telemetry/telemetry.ts:213
   executeTool?: <T>(options: {
     callId: string; toolCallId: string; execute: () => PromiseLike<T>;
   }) => PromiseLike<T>;
   ```

   `packages/otel` provides an OpenTelemetry implementation of this interface — that's where you wire Datadog / Honeycomb / etc.

### Cost (USD)

**`ai` does not compute cost.** No pricing tables, no `costUSD` field, no `tokenCost` helper. The only USD figures surface from the **AI Gateway** REST API (`packages/gateway/src/gateway-spend-report.ts:34-66`):

```ts
// packages/gateway/src/gateway-spend-report.ts:34
export interface GatewaySpendReportRow {
  day?: string; hour?: string; user?: string; model?: string; tag?: string; provider?: string;
  totalCost: number;       // ← USD
  marketCost?: number;      // ← USD
  inputTokens, outputTokens, cachedInputTokens, cacheCreationInputTokens, reasoningTokens, requestCount;
}
```

You query `gateway.getSpendReport({ startDate, endDate, groupBy: 'user' | 'model' | 'tag' | ..., tags, userId, model, provider, credentialType })` to aggregate. Caveat: only available when the model calls go through Vercel's AI Gateway (`@ai-sdk/gateway`). If you call OpenAI / Anthropic directly without the gateway, you compute cost yourself.

### Canonical "where do I read tokens"

```ts
const result = await agent.generate({ prompt: '...', runtimeContext: { tenantId } });

result.totalUsage.inputTokens;
result.totalUsage.outputTokens;
result.totalUsage.inputTokenDetails.cacheReadTokens;

for (const step of result.steps) {
  step.usage;                  // per-step
}

// Or as a callback:
new ToolLoopAgent({
  // ...
  onFinish: ({ totalUsage, runtimeContext, steps }) => {
    db.usage.insert({
      tenantId: runtimeContext.tenantId,
      stepCount: steps.length,
      inputTokens: totalUsage.inputTokens,
      outputTokens: totalUsage.outputTokens,
      cacheReadTokens: totalUsage.inputTokenDetails.cacheReadTokens,
    });
  },
});
```

## Architectural diagram

```
                          ┌────────────────────────────────┐
                          │   Frontend (React/Vue/Svelte)  │
                          │   useChat({ transport })       │
                          │   ChatState<UIMessage[]>       │
                          │   addToolApprovalResponse(...) │
                          └───────────────┬────────────────┘
                                          │
                          DefaultChatTransport       (HTTP/SSE, body: UIMessage[])
                          ├─ POST /api/chat   →  submit | regenerate (in body trigger)
                          └─ GET  /api/chat/:id/stream → resumable-stream reconnect
                                          │
                                          ▼
                ┌─────────────────────────────────────────────────────┐
                │  YOUR HTTP HANDLER  (Next.js / Express / Hono /...) │
                │                                                     │
                │   createAgentUIStreamResponse({ agent, uiMessages, │
                │     onStepFinish: persist(...) ,                   │
                │     consumeSseStream: resumableSink(...) })        │
                └───────────────────────┬─────────────────────────────┘
                                        │
                                        ▼
                ┌────────────────────────────────────────┐
                │      ToolLoopAgent<CALL_OPTIONS,       │
                │          TOOLS, RUNTIME_CONTEXT,       │
                │          OUTPUT>                       │
                │  ┌──────────────────────────────────┐  │
                │  │ prepareCall(opts)  ←─[hook]─┐    │  │
                │  └────────────┬─────────────────┘    │  │
                │               ▼                       │  │
                │  ┌──────────────────────────────────┐  │
                │  │  generateText / streamText       │  │
                │  │                                  │  │
                │  │  do {                            │  │
                │  │    prepareStep ←─[hook, per-step]│  │
                │  │    filterActiveTools             │  │
                │  │    notify onStepStart            │  │
                │  │    notify onLanguageModelCallStart│ │
                │  │                                  │  │
                │  │    LanguageModelMiddleware       │  │
                │  │      transformParams ← [hook]    │  │
                │  │      wrapStream ← [hook]         │  │
                │  │        model.doStream(...)       │  │
                │  │                                  │  │
                │  │    parseToolCall                 │  │
                │  │      experimental_refineToolInput│  │
                │  │      ←─[hook, per-tool-call]     │  │
                │  │    resolveToolApproval           │  │
                │  │      → user-approval = pause     │  │
                │  │                                  │  │
                │  │    parallel ∀ toolCall:          │  │
                │  │      notify onToolExecutionStart │  │
                │  │      executeTool                 │  │
                │  │        tool.execute(input, {     │  │
                │  │          context, abortSignal,   │  │
                │  │          messages, sandbox })    │  │
                │  │      notify onToolExecutionEnd   │  │
                │  │                                  │  │
                │  │    notify onStepFinish           │  │
                │  │  } while (more tool calls        │  │
                │  │     && !stopWhen)                │  │
                │  │                                  │  │
                │  │  notify onFinish                 │  │
                │  └──────────────────────────────────┘  │
                │                                        │
                │  StreamTextResult                      │
                │  .toUIMessageStream({                  │
                │    originalMessages, onStepFinish,    │
                │    onFinish: persist(...) })          │
                │  →  ReadableStream<UIMessageChunk>     │
                └────────────────────────────────────────┘
                                        │
                       JsonToSseTransformStream
                        (data: <json>\n\n / data: [DONE]\n\n)
                                        │
                                        ▼
                       Response (text/event-stream)
```

State (sessions, threads, message history, tenant data) lives entirely **outside** this diagram — you own it.

## Appendix — Files worth reading first

- `packages/ai/src/agent/agent.ts:138` — `Agent<CALL_OPTIONS, TOOLS, RUNTIME_CONTEXT, OUTPUT>` interface; the contract every agent implementation must satisfy.
- `packages/ai/src/agent/tool-loop-agent.ts:38` — the only concrete `Agent` shipped; ~270 LOC of `prepareCall` + delegation to `generateText` / `streamText`.
- `packages/ai/src/agent/tool-loop-agent-settings.ts:42` — every knob the `ToolLoopAgent` exposes; read this before designing your agent factory.
- `packages/ai/src/generate-text/generate-text.ts:653` — the actual `do...while` run loop (the meat of the SDK).
- `packages/ai/src/generate-text/prepare-step.ts:32` — `PrepareStepFunction` signature; this is the per-turn extension point.
- `packages/ai/src/generate-text/tool-approval-configuration.ts:111` — `ToolApprovalConfiguration`; the HITL gate spec (per-tool / global, returns `'approved' | 'denied' | 'user-approval'`).
- `packages/ai/src/generate-text/tool-input-refinement.ts:14` — `ToolInputRefinement`; how the harness mutates LLM-generated tool args before dispatch.
- `packages/provider-utils/src/types/tool-execute-function.ts:8` — `ToolExecutionOptions<CONTEXT>`; what every tool's `execute` receives at call time.
- `packages/ai/src/ui/chat.ts:237` — `AbstractChat`; the client-side state machine + `sendMessage` / `regenerate` / `addToolApprovalResponse` / `stop`.
- `packages/ai/src/ui-message-stream/ui-message-chunks.ts:225` — `UIMessageChunk` taxonomy; the canonical Data Stream Protocol on the wire.
- `packages/ai/src/ui-message-stream/json-to-sse-transform-stream.ts:6` — 12-line transform; the entire "framing" of the protocol.
- `packages/ai/src/telemetry/telemetry.ts:80` — `Telemetry` interface; what an OTel / Datadog integration implements.
- `packages/gateway/src/gateway-spend-report.ts:34` — `GatewaySpendReportRow`; the only USD-cost surface in the whole SDK.
- `examples/next-agent/app/api/chat/route.ts:1` — the entire minimal "agent over HTTP" wiring (10 LOC including imports).
- `examples/next/app/api/chat/route.ts:88` and `examples/next/app/api/chat/[id]/stream/route.ts:18` — the full durable-stream + cancel-from-anywhere recipe (uses the third-party `resumable-stream` package).
