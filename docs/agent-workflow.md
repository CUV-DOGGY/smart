# 第三阶段 Agent 工作流

## 职责边界

LangGraph Checkpoint 与产品聊天记录是两套不同数据：

- `agent_checkpoints` 和 `agent_checkpoint_writes` 保存图状态、中断和恢复位置。
- `conversations` 与 `conversation_messages` 保存用户可见的会话、标题和消息。
- 删除会话时先校验所有权，再同时删除产品记录和该用户线程的 Checkpoint。

线程键为 `user_id:conversation_id`。用户身份、LLM 和 Service Tool Registry 通过 `AgentRuntimeContext` 注入，不写入模型可见的工具参数，也不存入 Agent State。

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
  ├─ 只读 ─────▶ execute_tool ─▶ model
  └─ 写入 ─────▶ confirm_write (interrupt)
                         ├─ reject ─▶ END（零副作用）
                         └─ approve ─▶ execute_tool ─▶ model
```

State 只包含消息、当前工具、已收集槽位、缺失槽位、冻结写操作、批准决策和工具执行计数。每轮最多执行 4 次工具，图递归上限为 12，API 运行超时 90 秒。缺少 `order_id`、`shop_id`、`address_id` 或 `items` 时，下一轮会合并用户补充；用户也可以取消未完成任务。

## 工具清单

只读工具：

- `list_shops`、`list_products`
- `list_addresses`
- `list_orders`、`get_order`

受控写工具：

- `create_order`
- `cancel_order`
- `set_default_address`
- `delete_address`

工具层只负责 Pydantic 参数校验、安全 DTO 转换和 Service 调用。创建订单的幂等键由冻结的确认动作 ID 派生；恢复重试不会生成新的业务幂等键。工具结果是回复事实来源，没有成功 Tool Result 时，模型不得声称业务数据已经改变。

## 确认和并发

写操作在 `confirm_write` 节点调用 LangGraph `interrupt`。确认卡只展示服务端生成的动作名与安全摘要；客户端用 `conversation_id + interrupt_id + approve|reject` 调用 `/chat/resume`。普通消息不能绕过确认，也不能在批准时替换参数。

Redis 锁按用户和会话的 SHA-256 摘要分区，锁租约 120 秒。一个会话同一时刻只允许一个发送或恢复请求，Lua 脚本只释放属于当前运行令牌的锁。

## SSE 合约

- `meta`：`conversation_id`、`run_id`
- `status`：思考、校验或调用业务服务，不包含工具参数
- `token`：最终回复增量
- `confirmation_required`：`interrupt_id`、动作和安全摘要
- `done`：`completed` 或 `awaiting_confirmation`
- `error`：标准错误码、消息、`request_id`、`retryable`

前端在待确认时隐藏普通输入框，仅显示批准和拒绝。会话历史接口返回可选的 `pending_confirmation`，因此页面刷新或切换会话后仍能恢复确认卡。
