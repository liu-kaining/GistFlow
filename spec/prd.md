# 🚀 GistFlow - 项目宪法 (Part 1 & 2)

## 0. 项目总览 (Project Charter)

* **项目名称**：GistFlow (The Essence Flow)
* **核心目标**：构建一个自动化的 ETL 管道，从 Gmail 提取 Newsletter，通过 LLM 进行深度清洗、总结、评分，最终沉淀为 Notion 数据库中的结构化知识资产。
* **交付形态**：Dockerized Self-Hosted Application (Python)。
* **主要用户**：开发者本人（后期可扩展为开源工具）。

---

## Phase 1: 产品需求文档 (PRD)

### 1.1 核心用户故事 (User Stories)

1. **作为用户**，我希望只需配置一次 Gmail App Password 和 Notion Token，系统就能自动运行，无需人工干预。
2. **作为用户**，我希望系统只处理 Gmail 中带有特定标签（如 `Label: Newsletter`）的邮件，避免处理私人邮件。
3. **作为用户**，我希望 AI 能够识别邮件内容：
* 如果是**验证码/收据/单纯广告**：标记为垃圾，不写入 Notion（或写入 Log）。
* 如果是**长文/干货**：生成摘要、提取 3-5 个关键洞察（Insights）、提取提及的工具/链接、并给出一个“价值分（0-100）”。


4. **作为用户**，我希望在 Notion 中看到的不仅仅是摘要，还能展开看到清洗后的原文（Markdown 格式），以便溯源。
5. **作为用户**，我希望支持自定义 LLM 模型（DeepSeek, Gemini, OpenAI），因为我可能有 Token 成本或上下文窗口的偏好。

### 1.2 数据实体定义 (Data Entities)

**核心实体：ProcessedGist (经过 AI 处理后的信息单元)**
这也是系统内部流转的标准数据结构。

| 字段名 | 类型 | 描述 | 示例 |
| --- | --- | --- | --- |
| `source_id` | String | 邮件 Message-ID (用于去重) | `<abc@google.com>` |
| `title` | String | 邮件标题 (或 AI 优化后的标题) | "2024 AI 趋势报告" |
| `sender` | String | 发件人/品牌 | "Benedict Evans" |
| `received_at` | DateTime | 邮件接收时间 | 2024-05-20 09:00 |
| `summary` | String | 100字以内的 TL;DR | "本文分析了..." |
| `insights` | List[String] | 核心知识点列表 | ["Transformer 架构...", "GPU 瓶颈..."] |
| `score` | Integer | 价值打分 (0-100) | 85 |
| `tags` | List[String] | 自动分类标签 | ["AI", "Hardware"] |
| `raw_markdown` | String | 清洗后的正文 | (Markdown 内容) |
| `url` | String | 原始链接 (如有) | `http://...` |

### 1.3 边界条件 (Constraints & Scope)

* **Inbox Zero 策略**：处理成功的邮件，自动在 Gmail 中移除 `Newsletter` 标签，并加上 `GistFlow-Processed` 标签（归档）。
* **去重策略**：使用 SQLite 本地记录已处理的 `Message-ID`，防止重复消耗 Tokens。
* **错误处理**：LLM 可能会幻觉或超时，必须有 Retry 机制；HTML 解析失败不能导致整个服务崩溃。

---

## Phase 2: 技术架构设计 (Technical Architecture)

### 2.1 技术栈选型 (Tech Stack)

* **Runtime**: Python 3.11+ (强制使用 Type Hints)。
* **Container**: Docker (基于 `python:3.11-slim`)。
* **Core Libraries**:
* **Ingestion**: `imap-tools` (比 imaplib 更现代，易于维护)。
* **Parsing**: `beautifulsoup4` (HTML Cleaning), `markdownify` (HTML to MD)。
* **LLM Orchestration**: `langchain-core` + `langchain-openai` (标准化接口调用)。
* **Validation**: `pydantic` (V2) —— **这是核心**，用于强制 LLM 输出 JSON 并校验 Notion 格式。
* **Storage**: `notion-client` (官方 SDK)。
* **State**: `sqlite3` (标准库，无需额外服务)。
* **Scheduler**: `apscheduler` (定时任务)。
* **Config**: `pydantic-settings` (加载 .env)。



### 2.2 系统模块划分 (Module Design)

我们将项目结构分为 5 层，严格遵循“单一职责原则”。

```text
gistflow/
├── config/             # 配置层
│   └── settings.py     # Pydantic Settings (ENV加载)
├── core/               # 核心逻辑层
│   ├── ingestion.py    # Gmail IMAP Fetcher
│   ├── cleaner.py      # HTML -> Markdown 清洗器
│   ├── llm_engine.py   # AI 处理与结构化提取 (Prompt在这里)
│   └── publisher.py    # Notion API 写入逻辑
├── database/           # 本地持久化层
│   └── local_store.py  # SQLite 操作 (去重检查)
├── models/             # 数据模型层 (The Contract)
│   └── schemas.py      # Pydantic Models (ProcessedGist 定义)
├── utils/              # 工具层
│   └── logger.py       # 统一日志配置
├── main.py             # 程序入口 (Scheduler)
├── .env.example        # 环境变量模板
├── docker-compose.yml  # 编排文件
└── Dockerfile          # 镜像构建

```

### 2.3 关键数据流 (The Pipeline)

1. **Wake Up**: `Scheduler` 唤醒（每 30 分钟）。
2. **Fetch**: `ingestion.py` 连接 Gmail -> 搜索 Label -> 获取未读列表 -> **过滤掉已在 SQLite 中的 ID**。
3. **Clean**: `cleaner.py` 接收 HTML -> 去除 CSS/Scripts -> 转为 Markdown -> 截断过长文本 (Token Limit 保护)。
4. **Analyze (The Brain)**:
* `llm_engine.py` 组装 Prompt。
* 调用 LLM (DeepSeek/Gemini)。
* **强制输出 JSON** (Function Calling 或 JSON Mode)。
* `Pydantic` 校验 JSON 格式，失败则 Retry。


5. **Publish**: `publisher.py` 将 Pydantic 对象转换为 Notion Block 结构 -> 写入 Database -> 写入 Page Content。
6. **Archive**: `ingestion.py` 回调 Gmail，修改邮件标签。
7. **Commit**: 记录 Message-ID 到 SQLite。

### 2.4 开发规范 (Coding Standards for Cursor)

1. **Type Hints**: 所有函数必须包含完整的参数和返回类型注解 (`def func(a: int) -> str:`)。
2. **Docstrings**: 使用 Google Style Docstrings。
3. **Error Handling**: 不允许裸奔的 `try...except`，必须捕获特定异常并记录 Log。
4. **Configuration**: 所有硬编码（API Key, Model Name, Prompts）必须移入 `settings.py` 或环境变量。
5. **Log**: 使用 `loguru` 或标准 `logging`，禁止使用 `print`。