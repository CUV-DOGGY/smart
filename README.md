# SmartServe AI

SmartServe AI 是面向外卖交易履约场景的全栈智能客服项目。当前第二阶段已经打通真实登录态、流式 AI 会话、地址与地图、商品目录、订单创建/查询/取消，并以主仓库的 Service 层作为唯一业务入口。

## 能力概览

- OAuth2 密码登录、JWT 身份恢复、Redis 认证限流
- DeepSeek 兼容模型 SSE 流式回答、MongoDB 会话与消息历史
- 收货地址 CRUD、默认地址、高德地图选点、服务端二次地理校验
- 店铺/商品只读目录、服务端定价、库存事务预占、配送半径校验
- 幂等下单、订单历史/详情/取消和用户数据隔离
- 统一 API 错误体、请求 ID、基础设施健康检查

Agent、RAG、业务工具调用和 MCP 属于后续阶段；当前聊天模型不会声称已经执行订单或地址操作。

## 分层架构

```text
frontend/src
├─ app/                  路由、Store 与应用装配
├─ shared/               HTTP、环境、存储和通用布局
└─ features/
   ├─ auth/              登录态与认证页面
   ├─ chat/              会话、SSE 与消息组件
   ├─ address/           地址页面和表单
   ├─ map/               高德 SDK 适配器与地图组件
   └─ order/             目录、下单和订单页面

backend/app
├─ routers/              HTTP 与鉴权边界
├─ services/             业务规则和用例编排
├─ repositories/         MongoDB 持久化边界
├─ schemas/              公共请求与响应模型
└─ core/                 生命周期、中间件、错误和安全
```

业务域不直接访问其他域的内部状态。前端页面只使用本域 API；地址域只接收地图适配器产生的标准位置对象，不依赖高德 SDK 类型。后端 Router 不直接拼 MongoDB 查询，Service 不读取 HTTP 请求。

## 技术与版本

- Python 3.14.5：`E:\python312\python.exe`
- Node.js 24.15.0、npm 11
- FastAPI、Motor、Redis、LangChain OpenAI
- React 19、Redux Toolkit、React Router、Vite
- MongoDB 8.3 单节点副本集 `rs0`
- Redis 8.2 Alpine，Docker Desktop
- 高德 Web 服务与地图 JSAPI 2.0

## 首次安装

确认 MongoDB Windows 服务为 `rs0 PRIMARY`，Docker Desktop 已启动，然后运行：

```powershell
.\scripts\bootstrap.ps1
```

脚本会：

1. 校验 Python 3.14.5 与 Node.js 24.15.0。
2. 使用 `backend/uv.lock` 重建后端环境。
3. 使用 `frontend/package-lock.json` 执行 `npm ci`。
4. 仅在缺少时创建 `backend/.env` 和 `frontend/.env.local`，不会覆盖本地配置。

依赖变更必须同步锁文件：

```powershell
uv add --project backend package-name
Set-Location frontend
npm install package-name
```

## 配置

后端真实配置放在被忽略的 `backend/.env`：

```dotenv
MODEL_NAME=your-model-name
DEEPSEEK_API_KEY=replace-with-your-api-key
DEEPSEEK_BASE_URL=https://api.example.com
MONGODB_URL=mongodb://localhost:27017/?replicaSet=rs0
MONGODB_DB_NAME=smart_customer_service
REDIS_URL=redis://127.0.0.1:6380/0
AMAP_WEB_SERVICE_KEY=replace-with-your-amap-web-service-key
JWT_SECRET_KEY=replace-with-at-least-32-random-characters
RATE_LIMIT_KEY_SECRET=replace-with-a-different-32-character-secret
```

前端本地配置放在 `frontend/.env.local`：

```dotenv
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_AMAP_JS_KEY=replace-with-your-amap-jsapi-key
VITE_AMAP_SECURITY_JS_CODE=replace-with-your-amap-security-js-code
```

`AMAP_WEB_SERVICE_KEY` 与 Web 端 JSAPI Key 是不同平台类型。`VITE_*` 会进入浏览器包，静态安全密钥只适用于本地演示；生产环境应切换到高德安全代理方式。任何真实密钥都不能提交。

## 店铺和商品数据

应用不会自动创建业务演示数据。请在 MongoDB 中手工写入：

- `shops`：店铺状态、营业时间、起送金额、配送费、位置和配送半径。
- `products`：商品名、价格、库存与上下架状态。

完整字段和可直接改写的 `mongosh` 示例见 [MongoDB 店铺与商品数据契约](docs/mongodb-catalog.md)。订单页在集合为空时会显示准备说明。

## 启动

```powershell
.\scripts\dev.ps1
```

脚本会启动/检查 Redis，确认 MongoDB，后台运行 Uvicorn，然后以前台方式运行 Vite。退出 Vite 后只清理由该脚本创建的后端进程。

- 前端：`http://127.0.0.1:5173`
- Swagger：`http://127.0.0.1:8000/docs`
- 存活：`http://127.0.0.1:8000/health/live`
- 就绪：`http://127.0.0.1:8000/health/ready`
- 后端运行日志：`.runtime-logs/`

Redis 容器为 `smartserve-redis`，只绑定 `127.0.0.1:6380`；6379 保留给已有项目。AOF 数据存放在命名卷 `smartserve_redis_data`。

## 公共 API

### 认证

- `POST /auth/register`
- `POST /auth/login`
- `GET /auth/me`

### 智能客服

- `POST /chat/stream`
- `GET /conversations`
- `GET /conversations/{conversation_id}/messages`
- `DELETE /conversations/{conversation_id}`

流事件依次为 `meta`、若干 `token`、`done`；模型失败时为 `error`。客户端不提交 UID，所有权只由 Bearer Token 决定。

### 地址、目录与订单

- `GET|POST /addresses`
- `GET|PUT|DELETE /addresses/{address_id}`
- `POST /addresses/{address_id}/set-default`
- `GET /catalog/shops`
- `GET /catalog/shops/{shop_id}/products`
- `GET|POST /orders`
- `GET /orders/{order_id}`
- `POST /orders/{order_id}/cancel`

下单必须携带 `Idempotency-Key`。价格、库存、店铺状态、地址归属和配送范围均由服务端重新确认。

## 错误协议

所有普通 HTTP 错误使用统一结构，响应头同时提供 `X-Request-ID`：

```json
{
  "code": "ADDRESS_NOT_FOUND",
  "message": "收货地址不存在",
  "field_errors": [],
  "request_id": "a-request-id"
}
```

SSE 已开始后的模型错误使用同样的 `code/message/request_id` 字段发送 `error` 事件，不向浏览器返回连接串、密钥或异常栈。

## 测试

运行后端单元测试、前端 ESLint、Vitest 和生产构建：

```powershell
.\scripts\test.ps1
```

额外运行真实 MongoDB 事务和会话集成测试：

```powershell
.\scripts\test.ps1 -Integration
```

集成测试只使用以 `_test` 结尾的数据库，并清理自身创建的订单、会话与消息。LLM 单元测试使用假模型，不消耗真实 API 额度。

## 常见问题

### 地图提示未配置

确认 `frontend/.env.local` 同时填写 Web 端 JSAPI Key 和对应安全密钥，修改后重启 Vite。后端 Web 服务 Key 不能代替 JSAPI Key。

### 下单页没有店铺

按 `docs/mongodb-catalog.md` 写入 `shops/products`，并确保店铺为启用、接单和当前营业状态。

### MongoDB 事务失败

连接串必须包含 `replicaSet=rs0`，`replSetGetStatus` 必须显示 PRIMARY。standalone MongoDB 不支持本项目的库存与订单事务。

### Docker 命令不存在

脚本会自动识别 `%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin\docker.exe`。若仍失败，请先启动 Docker Desktop。

## 后续融合路线

1. 将现有 Service 注册为 LangGraph 工具，客服通过工具而不是直接访问 Repository。
2. 迁移地图 Demo 的 MCP Schema 与严格校验测试，不复制业务实现。
3. 增加知识库 RAG、Agent 评测集、链路追踪、成本与延迟指标。
