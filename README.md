# Northstar 工程项目 AI 助理

面向工程项目资料的 AI 工作台，支持项目管理、资料管理、文档解析、RAG 检索、AI 问答、引用与文档预览，并逐步扩展 Memory、Agent、MCP 等能力。

## 当前状态

Northstar 目前处于持续开发阶段。基础工程、用户认证、项目管理、资料中心、Assistant/RAG、会话上下文以及 PDF/DOCX 文档预览等核心基础能力已经完成，可组成完整的本地开发工作流。

Memory、Agent、MCP 以及更完整的工程业务能力仍在持续建设中。本仓库不代表所有规划能力均已完成，风险中心和部分设置能力目前仅提供工作台入口与明确的“即将开放”状态。

## 已实现功能

### 1. 用户认证

- 用户注册与登录
- Bearer JWT 认证
- 当前用户身份解析
- 项目访问权限基础校验

### 2. 项目管理

- 真实项目列表
- 创建项目
- 项目详情展示
- 当前项目上下文
- 项目切换以及相关资料、会话上下文同步切换

### 3. 项目资料中心

- 当前项目的真实资料列表
- 受认证保护的文件上传
- 同名文档版本管理
- `current` / `version` 语义
- ingestion 状态展示
- 失败文件重新入库（reingest）
- 用户与项目级资料访问隔离

当前前端上传白名单以 PDF、DOCX 为主，不会为未支持的格式伪造预览内容。

### 4. 文档解析与预览

#### PDF

- 使用 PDF.js 和 Canvas 渲染真实 PDF 内容
- 多页连续阅读与统一滚动
- 真实页码显示及页码跳转
- 50%～300% 放大、缩小与缩放比例选择
- 适应宽度、适应页面
- 当前版本与历史版本切换

#### DOCX

- 服务端基于 `python-docx` 解析，前端结构化渲染
- 标题、段落、列表和表格预览
- 不依赖不受认证保护的公开文件 URL
- 对暂未进行高保真渲染的图片给出真实提示，不伪造图片内容或 Word 物理分页

### 5. AI Assistant / RAG

- 基于当前项目的 AI 问答
- 从项目资料中检索证据
- 当前版本优先检索，同时支持历史版本解析
- Citation / 来源引用
- Markdown 渲染与 DOMPurify 内容净化
- 无有效证据时返回 `no_evidence`，不强行编造答案
- 对 LLM 不可用、RAG 不可用等异常进行结构化状态处理

### 6. 多轮会话上下文

- 请求携带 `conversation_id`
- 按用户、项目、会话三层隔离上下文
- 前端保存对话入口、标题、置顶状态及消息快照
- 当前会话内维护文档上下文
- 支持“它”“这份文件”“上一版”“最新版”等文档与版本指代
- 多文件明确引用时进行歧义识别与边界处理

当前会话上下文不等同于完整的长期 Memory。Memory 尚未作为完整持久化记忆层接入生产 Assistant。

### 7. 当前工作台 UI

- Vue 3 + TypeScript + Vite
- 全局 Header 与可折叠 Sidebar
- 项目、资料、助理、风险、设置等模块入口
- 动态双栏工作台：主工作区 + 当前模块的列表/资源/上下文面板
- 项目模块：项目详情 + 项目列表
- 资料模块：文件内容预览 + 项目资料列表
- 助理模块：AI Assistant + 我的对话
- Context Panel 可关闭、恢复和调整宽度
- 深色 Sidebar 与响应式布局

## 技术栈

### 后端

- Python 3.12+
- FastAPI / Uvicorn
- SQLite
- JWT（PyJWT）
- PyMuPDF / pypdf
- python-docx
- Qdrant Client
- Sentence Transformers
- OpenAI-compatible API

### 前端

- Vue 3
- TypeScript
- Vite
- PDF.js（`pdfjs-dist`）
- marked
- DOMPurify

### 基础设施

- Docker Compose
- Qdrant

## 项目结构

以下为当前仓库的核心结构：

```text
.
├─ frontend/
│  ├─ src/
│  │  ├─ App.vue
│  │  ├─ main.ts
│  │  ├─ style.css
│  │  └─ services/
│  │     └─ api.ts
│  ├─ package.json
│  └─ vite.config.ts
├─ backend/
│  ├─ app/
│  │  ├─ agent/
│  │  ├─ api/
│  │  ├─ auth/
│  │  ├─ memory/
│  │  ├─ services/
│  │  └─ main.py
│  ├─ tests/
│  ├─ requirements.txt
│  └─ .env.example
├─ docker-compose.yml
└─ README.md
```

## 本地运行

### 1. 准备后端环境变量

复制环境变量模板，并只在本地填写安全随机的 JWT 密钥及所需的模型服务配置：

```powershell
Copy-Item backend/.env.example backend/.env
```

不要把 `backend/.env`、API Key、JWT Secret 或密码提交到 Git。

### 2. 启动 Qdrant

在项目根目录运行：

```powershell
docker compose up -d qdrant
```

当前 Compose 配置将 Qdrant 绑定到本机 `6333`（HTTP）和 `6334`（gRPC）端口。

### 3. 启动后端

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8002
```

- API：`http://127.0.0.1:8002`
- 健康检查：`http://127.0.0.1:8002/api/health`
- OpenAPI 文档：`http://127.0.0.1:8002/docs`

后端从 `backend/.env` 读取本地认证、Qdrant 和模型服务配置。README 不提供任何真实密钥。

### 4. 启动前端

另开一个终端：

```powershell
cd frontend
npm install
npm run dev
```

Vite 开发服务器默认地址为 `http://127.0.0.1:5173`（也可通过 `http://localhost:5173` 访问），前端默认连接 `http://127.0.0.1:8002` 的后端 API。

前端类型检查和生产构建：

```powershell
npx tsc --noEmit --pretty false
npm run build
```

## 当前开发路线

### 已完成

- 基础工程与本地开发环境
- 用户注册、登录与 JWT 认证
- 项目管理
- 项目资料中心与版本管理
- PDF/DOCX 文档解析与预览
- RAG 基础检索能力
- AI Assistant
- Citation / 来源引用
- `conversation_id` 与会话上下文隔离
- 动态双栏工作台 UI

### 建设中

- 完整持久化 Memory
- 更完整的 Agent 能力与任务编排
- MCP 集成
- 更完整的工程业务能力
- 更完善的文档指代、歧义处理与边界覆盖

## 注意事项

- `backend/.env` 不应提交到 Git。
- API Key、JWT Secret、密码等敏感信息不得写入源码或文档。
- 本地工程资料、上传文件、数据库及其他运行时数据不应提交到 Git。
- Qdrant 是当前本地 RAG 开发依赖，可通过 Docker Compose 启动。
- 项目仍处于持续开发阶段，尚未完成的模块会明确标注，不应被视为生产完备能力。
