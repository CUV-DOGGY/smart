# 第三阶段 Agent 工作流

## 职责边界

LangGraph Checkpoint、写命令和产品聊天记录是三套边界清晰的数据：

- `agent_checkpoints` 和 `agent_checkpoint_writes` 保存图状态、中断和恢复位置。
- `write_commands` 保存冻结参数、用户决策、业务执行状态、幂等结果和图恢复状态。
- `conversations` 与 `conversation_messages` 保存用户可见的会话、标题和消息。
- 删除会话时先校验所有权，再删除产品记录和该用户线程的 Checkpoint；写命令作为审计记录保留。

线程键为 `user_id:conversation_id`。用户身份、LLM、只读工具和 Write Command Gateway 通过 `AgentRuntimeContext` 注入，不进入模型参数。LangGraph 对订单、库存和地址等业务数据只读；它可以创建编排命令和保存 Checkpoint，但不能直接执行业务写入。

## 图流程

```text
START
  │
  ▼
model ──无工具──▶ END
  │
  ▼
validate_tool
  ├─ 缺参 ─────▶ clarify ─▶ END
  ├─ 只读 ─────▶ execute_read_tool ─▶ model
  └─ 写入 ─────▶ prepare_write_command
                         │
                         ▼
                   confirm_write (interrupt)
                         │
                         │ 图外状态机完成 reject 或业务执行
                         ▼
                   append_write_result ─▶ model
```

State 只包含消息、当前工具、已收集槽位、缺失槽位、写命令引用、批准决策和工具执行计数。冻结参数只保存在 `write_commands`，Checkpoint 不再是可执行参数的事实来源。每轮最多执行 4 次工具，图递归上限为 12，API 运行超时 90 秒。

## 工具清单

只读工具：

- `list_shops`、`list_products`
- `list_addresses`
- `list_orders`、`get_order`

写命令类型：

- `create_order`
- `cancel_order`
- `set_default_address`
- `delete_address`

`execute_read_tool` 只能调用只读 Service，检测到写工具会直接拒绝。写命令执行器在图外调用业务 Service；`append_write_result` 只读取命令终态并追加 ToolMessage。创建订单使用 `command:{command_id}` 作为领域幂等键。没有成功的命令结果时，模型不得声称业务数据已经改变。

## 确认和并发

写操作在 `confirm_write` 节点调用 LangGraph `interrupt`。确认卡只展示服务端生成的动作名、安全摘要和过期时间。客户端用 `conversation_id + interrupt_id + approve|reject` 调用 `/chat/resume`，并复用 `Idempotency-Key` 请求头。普通消息不能绕过确认，批准请求也不能提交或替换冻结参数。

`/chat/resume` 先幂等记录决策，再由 Write Command Executor 将业务修改与命令终态放进同一个 MongoDB 事务。命令达到 `succeeded`、`rejected`、`conflict`、`failed` 或 `expired` 后才恢复 LangGraph。命令 ID 保证业务执行幂等，决策幂等键保证 HTTP 重试幂等，确定性的助手消息 ID 保证回复落库幂等。

Redis 锁限制同一会话并发；MongoDB 条件更新、唯一索引和执行租约才是持久化幂等边界。正常命令在确认请求内执行，恢复 Worker 只接管超过宽限期的 approved 命令和过期的 executing 租约。

## SSE 合约

- `meta`：`conversation_id`、`run_id`
- `status`：思考、校验或调用业务服务，不包含工具参数
- `token`：最终回复增量
- `confirmation_required`：`interrupt_id`、`command_id`、`expires_at`、动作和安全摘要；创建订单时额外携带服务端计价的 `presentation`
- `done`：`completed` 或 `awaiting_confirmation`
- `error`：标准错误码、消息、`request_id`、`retryable`

前端在待确认时隐藏普通输入框，仅显示批准和拒绝，并为同一命令复用决策幂等键。订单确认表不解析模型文本；执行前服务端重新生成确认哈希，价格、配送费或地址变化时命令进入 `conflict`，不会静默按新内容执行。会话历史接口返回可选的 `pending_confirmation`，因此页面刷新或切换会话后仍能恢复确认卡。
