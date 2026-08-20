# SmartServe AI

SmartServe AI 是正在融合中的外卖交易履约智能客服平台。本仓库是三个原型项目的融合主仓库；第一阶段已经建立可复现的后端工程基线，后续阶段将接入聊天前端、LangGraph Agent 和 MCP 适配层。

当前后端包含用户认证、Redis 限流、地址与高德地理编码、配送范围校验、订单创建与取消、库存预占、幂等控制和统一异常处理。`/chat` 仍是下一阶段待实现能力。

## 技术栈

- Python 3.14.5、uv
- FastAPI、Pydantic、Uvicorn
- MongoDB 8.3 单节点副本集
- Redis 8.2（Docker Desktop）
- LangChain OpenAI / DeepSeek 兼容接口
- 高德地图 Web 服务
- unittest

## 本地架构

```text
Windows
├─ E:\python312\python.exe        Python 3.14.5
├─ MongoDB Windows Service        localhost:27017 / rs0
├─ Docker Desktop
│  └─ smartserve-redis            127.0.0.1:6380
└─ FastAPI                        127.0.0.1:8000
```

MongoDB 使用原生 Windows 服务；Redis 使用容器；FastAPI 使用本仓库的 uv 虚拟环境运行。

## 环境要求

- `E:\python312\python.exe`，版本必须为 3.14.5
- [uv](https://docs.astral.sh/uv/)
- MongoDB 8.3，已启用副本集 `rs0`
- [Docker Desktop for Windows](https://docs.docker.com/desktop/setup/install/windows-install/)
- 可用的 DeepSeek 兼容模型配置和高德 Web 服务 Key

确认 Python：

```powershell
& "E:\python312\python.exe" --version
```

确认 MongoDB：

```powershell
& "E:\python312\python.exe" -c "from pymongo import MongoClient; c=MongoClient('mongodb://localhost:27017/?replicaSet=rs0'); s=c.admin.command('replSetGetStatus'); print(s['set'], s['members'][0]['stateStr'])"
```

预期输出包含 `rs0 PRIMARY`。MongoDB 配置至少需要：

```yaml
net:
  port: 27017
  bindIp: 127.0.0.1
replication:
  replSetName: rs0
```

## 首次安装

在仓库根目录运行：

```powershell
.\scripts\bootstrap.ps1
```

脚本会验证 Python 3.14.5，并根据 `backend/uv.lock` 创建 `backend/.venv`。如果 `backend/.env` 不存在，脚本只会从 `.env.example` 创建一次，不会覆盖已有配置。

依赖变更统一使用 uv，并同时提交 `pyproject.toml` 与 `uv.lock`：

```powershell
uv add --project backend package-name
uv remove --project backend package-name
uv sync --project backend --locked --python E:\python312\python.exe
```

## 环境变量

编辑被 Git 忽略的 `backend/.env`，不要把真实密钥提交到仓库。主要配置：

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

完整字段和安全说明见 `backend/.env.example`。

## 启动开发环境

先确保 MongoDB Windows 服务和 Docker Desktop 已启动，然后运行：

```powershell
.\scripts\dev.ps1
```

脚本会启动 Redis、检查 MongoDB 和 Redis，再以前台热重载模式启动 FastAPI。常用地址：

- Swagger：`http://127.0.0.1:8000/docs`
- 存活检查：`http://127.0.0.1:8000/health/live`
- 就绪检查：`http://127.0.0.1:8000/health/ready`

只管理 Redis：

```powershell
$docker = (Get-Command docker -ErrorAction SilentlyContinue).Source
if (-not $docker) { $docker = Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\resources\bin\docker.exe" }
& $docker compose -f infra\compose.dev.yml up -d --wait redis
& $docker compose -f infra\compose.dev.yml ps
& $docker compose -f infra\compose.dev.yml stop redis
```

Redis 仅绑定本机回环地址的 6380 端口，并使用命名卷 `smartserve_redis_data` 保存 AOF 数据。6379 保留给当前已存在的其他项目 Redis 容器。

## 健康检查

- `GET /health/live` 只检查 FastAPI 进程，正常返回 `{"status":"ok"}`。
- `GET /health/ready` 并行检查 MongoDB 与 Redis。全部正常返回 HTTP 200；任何组件不可用返回 HTTP 503。
- 就绪响应只暴露 `ok` 或 `unavailable`，不会返回连接字符串和底层异常。
- DeepSeek 和高德属于按请求调用的外部依赖，不纳入启动就绪检查。

## 测试

运行全部单元测试：

```powershell
.\scripts\test.ps1
```

额外运行真实 MongoDB 集成测试：

```powershell
.\scripts\test.ps1 -Integration
```

集成测试只允许使用以 `_test` 结尾的数据库名，并在结束时删除自己创建的测试订单。测试配置使用独立占位值，不依赖开发者的真实 `.env`。

## 常见问题

### Docker 命令不存在

安装并启动 Docker Desktop，重新打开 PowerShell。开发脚本也会自动识别 `%LOCALAPPDATA%\Programs\DockerDesktop` 下的 per-user 安装。

### Redis 启动失败

确认 6380 端口未被占用：

```powershell
Get-NetTCPConnection -LocalPort 6380 -ErrorAction SilentlyContinue
& "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin\docker.exe" compose -f infra\compose.dev.yml logs redis
```

### MongoDB 事务失败

确认连接串包含 `replicaSet=rs0`，并确认 `replSetGetStatus` 显示 PRIMARY。standalone MongoDB 不能运行项目中的多文档事务。

### PowerShell 不允许运行脚本

不需要永久修改系统策略，可以仅为单次进程执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1
```

## 后续融合路线

1. 接入客服助手的 React 会话界面和真实登录态。
2. 以升级版 Service 为唯一业务入口，实现 LangGraph 工具调用和真实 SSE。
3. 迁移地图 Demo 的严格校验测试与 MCP Schema，不复制业务层。
4. 增加知识库 RAG、Agent 评测集、链路追踪和面试演示流程。
