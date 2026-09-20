# Northstar 工程项目 AI 助理

这是一个面向工程项目团队的产品雏形，当前聚焦于「像真正产品一样可使用的工作台」和可扩展的前后端基础设施。复杂的 AI、RAG、Memory、MCP 能力暂不接入，界面和 API 契约已为后续迭代预留。

## 技术栈

- 前端：React、TypeScript、Vite、Lucide React
- 后端：Python、FastAPI、Uvicorn
- 前后端通过 Vite 开发代理访问 `/api`

## 启动

### 1. 启动后端

```bash
cd backend
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

后端地址：`http://127.0.0.1:8000`  
健康检查：`GET http://127.0.0.1:8000/api/health`，返回 `{"status":"ok"}`  
接口文档：`http://127.0.0.1:8000/docs`

### 2. 启动前端

```bash
cd frontend
npm install
npm run dev
```

前端地址：`http://localhost:5173`

生产构建：`npm run build`，预览构建结果：`npm run preview`。

## 页面与交互

- **项目**：项目列表入口（当前为占位页）。
- **资料**：资料管理入口（当前为占位页）。
- **助理**：主工作台。包含欢迎语、项目状态、快捷问题卡片、对话流、输入框、文件上传和右侧项目概览。
- **风险**：风险识别入口（当前为占位页，导航显示 3 条示例风险提醒）。
- **设置**：工作区设置入口（当前为占位页）。

主工作台中的快捷问题和发送按钮可实际操作；上传文件会将文件加入右侧示例资料列表（仅保存在浏览器内存中）。前端加载时会请求后端健康检查，并在输入区显示连接状态。

## 当前占位功能

- 对话回复为本地占位文案，不调用模型。
- 文件上传只更新前端列表，不做持久化、解析或权限校验。
- 搜索弹窗已预留交互，资料索引接入后启用。
- 项目切换、新建项目、资料详情和“查看全部资料”按钮暂未连接业务接口。

## 后续计划

1. 接入项目、成员、文件的持久化数据模型与鉴权。
2. 增加文件上传存储、解析、版本管理和全文检索。
3. 在 `backend/app/api/routes` 增加对话、风险、资料等领域路由，并在前端 `src/services` 中扩展 API 客户端。
4. 接入 AI、RAG、Memory、MCP 编排，补充流式响应、引用来源和审计日志。
5. 增加自动化测试、错误监控与部署配置。
