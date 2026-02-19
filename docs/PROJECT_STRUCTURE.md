# GistFlow 项目结构说明

## 📁 目录结构

```
GistFlow/
├── 📄 README.md                    # 项目主文档（快速开始、功能概览）
├── 📄 requirements.txt             # Python 依赖列表
├── 📄 pyproject.toml              # 项目元数据和构建配置
├── 📄 Dockerfile                   # Docker 镜像构建文件
├── 📄 docker-compose.yml          # Docker Compose 编排配置
├── 📄 .env.example                # 环境变量配置模板（需复制为 .env）
├── 📄 .gitignore                  # Git 忽略规则
│
├── 📁 gistflow/                    # 主代码包
│   ├── __init__.py
│   ├── 📁 config/                  # 配置管理
│   │   ├── __init__.py            # 导出 Settings, ensure_env_file, get_settings, reload_settings
│   │   └── settings.py           # Pydantic Settings + ensure_env_file()
│   │
│   ├── 📁 core/                    # 核心业务逻辑
│   │   ├── __init__.py            # 导出所有核心模块
│   │   ├── ingestion.py           # Gmail IMAP 邮件获取（EmailFetcher）
│   │   ├── cleaner.py             # HTML→Markdown 清洗（ContentCleaner）
│   │   ├── llm_engine.py          # LLM 智能提取（GistEngine）
│   │   ├── publisher.py            # Notion 发布（NotionPublisher）
│   │   └── local_publisher.py     # 本地文件存储（LocalPublisher）
│   │
│   ├── 📁 database/                # 数据持久化
│   │   ├── __init__.py            # 导出 LocalStore
│   │   └── local_store.py         # SQLite 数据库操作（去重、错误记录、Prompt 历史）
│   │
│   ├── 📁 models/                  # 数据模型
│   │   ├── __init__.py            # 导出 Gist, RawEmail 等
│   │   └── schemas.py             # Pydantic 数据模型定义
│   │
│   ├── 📁 utils/                   # 工具模块
│   │   ├── __init__.py
│   │   └── logger.py              # 日志配置（setup_logger）
│   │
│   └── 📁 web/                     # Web 管理界面
│       ├── __init__.py            # 导出 create_app
│       ├── api.py                 # Flask REST API 路由
│       └── 📁 static/
│           └── index.html         # 单页应用（仪表盘、Prompt 管理、配置、任务）
│
├── 📁 prompts/                     # Prompt 模板文件（可挂载编辑）
│   ├── system_prompt.txt          # System Prompt 模板
│   └── user_prompt_template.txt   # User Prompt 模板
│
├── 📁 tests/                       # 测试文件
│   ├── __init__.py
│   ├── test_config.py             # 配置测试
│   ├── test_ingestion.py          # 邮件获取测试
│   ├── test_llm_engine.py         # LLM 引擎测试
│   ├── test_publisher.py          # Notion 发布测试
│   ├── test_pipeline.py           # 完整流程测试
│   └── check_notion_db.py         # Notion 数据库配置检查工具
│
├── 📁 docs/                        # 文档目录
│   ├── README.md                  # 文档导航
│   ├── GUIDE.md                   # 完整使用指南（Docker、Notion、Web、故障排查）
│   ├── CODE_REVIEW.md             # 代码审查报告
│   ├── DEV_READINESS.md           # 开发准备摘要
│   ├── PROJECT_STRUCTURE.md       # 项目结构说明（本文件）
│   └── 📁 spec/                    # 项目规范文档
│       ├── prd.md                 # 产品需求文档
│       ├── tech_init.md           # 技术初始化文档
│       ├── tech_process.md        # 技术流程文档
│       ├── MANIFESTO.md           # 项目宪章
│       ├── AI_GUIDELINES.md       # AI 编码规范
│       └── .do.md                 # 开发操作指南
│
├── 📁 data/                        # 运行时数据目录（.gitignore，不提交）
│   └── gists/                     # 本地存储的 Gist 文件（如果启用）
│
├── 📁 logs/                        # 日志文件目录（.gitignore，不提交）
│
└── 📄 main.py                      # 主程序入口（GistFlowPipeline 编排）
```

## 📋 文件分类说明

### 根目录文件

| 文件 | 用途 | 是否提交 |
|------|------|----------|
| `README.md` | 项目主文档 | ✅ |
| `requirements.txt` | Python 依赖 | ✅ |
| `pyproject.toml` | 项目元数据 | ✅ |
| `Dockerfile` | Docker 构建 | ✅ |
| `docker-compose.yml` | Docker 编排 | ✅ |
| `.env.example` | 配置模板 | ✅ |
| `.env` | 实际配置（含密钥） | ❌ |
| `.gitignore` | Git 忽略规则 | ✅ |
| `main.py` | 程序入口 | ✅ |

### 代码目录（gistflow/）

- **config/**：配置管理，使用 Pydantic Settings
- **core/**：核心业务逻辑（ETL 管道各阶段）
- **database/**：SQLite 数据库操作（线程安全）
- **models/**：Pydantic 数据模型（数据契约）
- **utils/**：工具函数（日志等）
- **web/**：Flask Web API 和静态页面

### 资源目录

- **prompts/**：Prompt 模板文件，可通过 Docker volume 挂载编辑
- **tests/**：测试文件和工具脚本

### 文档目录（docs/）

- **用户文档**：GUIDE.md（完整使用指南）
- **开发文档**：DEV_READINESS.md、CODE_REVIEW.md
- **规范文档**：spec/ 目录下的设计文档

### 运行时目录（不提交）

- **data/**：SQLite 数据库、本地存储的 Gist 文件
- **logs/**：日志文件

## 🔧 目录组织原则

1. **代码与配置分离**：代码在 `gistflow/`，配置在根目录（`.env`, `docker-compose.yml`）
2. **文档集中管理**：所有文档在 `docs/`，用户文档与规范文档分离
3. **运行时数据隔离**：`data/` 和 `logs/` 通过 `.gitignore` 排除
4. **测试独立目录**：所有测试在 `tests/`，便于运行和维护
5. **资源文件可挂载**：`prompts/` 可通过 Docker volume 挂载，便于编辑

## 📝 注意事项

1. **不要提交**：
   - `.env`（包含敏感信息）
   - `data/` 目录（运行时数据）
   - `logs/` 目录（日志文件）
   - `prompts/.history/`（Prompt 历史存储在数据库）

2. **必须提交**：
   - `.env.example`（配置模板）
   - 所有代码文件
   - 所有文档文件
   - `prompts/*.txt`（Prompt 模板文件）

3. **Docker 挂载**：
   - `./data:/app/data` - 数据库持久化
   - `./logs:/app/logs` - 日志持久化
   - `./prompts:/app/prompts` - Prompt 文件可编辑
