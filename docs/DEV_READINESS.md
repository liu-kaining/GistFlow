# GistFlow 开发准备摘要

> 全面阅读代码与文档后的开发参考。用于快速进入开发状态。

---

## 1. 项目定位与规范

### 核心使命
- **输入**：Gmail Newsletter（带标签的邮件）
- **输出**：Notion 结构化知识 + 可选本地 Markdown/JSON
- **原则**：Fail Gracefully、Prompt is Logic、Type Safety、无 print、无裸 except

### 技术栈（必须遵守）
| 层级 | 技术 |
|------|------|
| 配置 | pydantic-settings，禁止散落 `os.getenv` |
| 数据 | pydantic V2，所有跨模块数据用 Pydantic 模型 |
| 日志 | loguru |
| 重试 | tenacity（所有外部 API） |
| 邮箱 | imap-tools |
| LLM | langchain-core + langchain-openai |
| Notion | notion-client |
| 调度 | apscheduler |
| Web | Flask（单容器，非前后端分离） |

### 编码规范（AI_GUIDELINES / MANIFESTO）
- 全部函数有类型注解和 Google Style Docstrings
- 捕获具体异常，用 tenacity 装饰外部调用
- 配置与 Prompt 进 settings / 环境变量 / 文件
- 禁止：硬编码密钥、print、超大 try-except、循环导入

---

## 2. 项目结构（实际）

```
GistFlow/
├── main.py                    # 入口：GistFlowPipeline，调度 + Web 线程
├── gistflow/
│   ├── config/
│   │   ├── __init__.py        # 导出 Settings, ensure_env_file, get_settings, reload_settings
│   │   └── settings.py       # Pydantic Settings + ensure_env_file()
│   ├── core/
│   │   ├── ingestion.py       # EmailFetcher：IMAP、标签匹配、去重、mark_as_processed
│   │   ├── cleaner.py        # ContentCleaner：HTML→Markdown、去噪、截断
│   │   ├── llm_engine.py     # GistEngine：LangChain、结构化 Gist、Prompt 文件/热重载
│   │   ├── publisher.py      # NotionPublisher：建页、属性映射、分块 append
│   │   └── local_publisher.py# LocalPublisher：Markdown/JSON 落盘
│   ├── database/
│   │   └── local_store.py    # SQLite，线程本地连接，processed_emails / processing_errors / prompt_history
│   ├── models/
│   │   └── schemas.py        # Gist, RawEmail, ProcessingResult, NotionPageContent
│   ├── utils/
│   │   └── logger.py         # setup_logger
│   └── web/
│       ├── __init__.py       # create_app
│       ├── api.py            # Flask 路由：health, config, prompts, tasks, stats
│       └── static/
│           └── index.html    # 单页：仪表盘 / Prompt 管理 / 配置 / 任务
├── prompts/                   # system_prompt.txt, user_prompt_template.txt（可挂载）
├── tests/                     # test_config, test_ingestion, test_llm_engine, test_publisher, test_pipeline, check_notion_db
├── docs/
│   ├── GUIDE.md              # 用户向：Docker、Notion、Web、故障排查
│   ├── README.md              # 文档导航
│   ├── CODE_REVIEW.md        # 代码审查
│   └── spec/
│       ├── prd.md            # 产品需求、数据实体、边界
│       ├── tech_init.md      # 数据契约 Gist、Notion Schema、Prompt 设计
│       ├── tech_process.md   # 组件规格（Settings, EmailFetcher, Cleaner, GistEngine, Publisher）
│       ├── MANIFESTO.md      # 项目宪章、哲学、风险、路线图、开发宪法
│       ├── AI_GUIDELINES.md  # AI 编码与架构标准
│       └── .do.md            # 分步实施指引
├── Dockerfile                 # 多阶段，国内镜像，复制 .env.example
├── docker-compose.yml        # env_file: .env, volumes: data/logs/prompts, port 5800
├── .env / .env.example
└── requirements.txt
```

---

## 3. 数据流（Pipeline）

1. **Wake**：APScheduler 按 `CHECK_INTERVAL_MINUTES` 触发 `run_once()`
2. **Fetch**：`EmailFetcher` 连接 Gmail → 按 `TARGET_LABEL` 搜索 → 排除 `LocalStore` 已处理 Message-ID → 返回 `List[RawEmail]`
3. **Clean**：`ContentCleaner.clean()`：HTML→Markdown、去噪、截断（MAX_CONTENT_LENGTH / HEAD/TAIL）
4. **Analyze**：`GistEngine.extract_gist()`：组装 Prompt → LLM 结构化输出 → Pydantic 校验为 `Gist`，失败 retry/返回 None
5. **Publish**：  
   - 有价值（`gist.is_valuable(MIN_VALUE_SCORE)`）：`NotionPublisher.push()`、可选 `LocalPublisher.push()`  
   - 写入 Notion 后得到 `notion_page_id`，写入本地得到 `local_file_path`
6. **Archive**：`LocalStore.mark_processed(...)`；`EmailFetcher.mark_as_processed(message_id)`（移除标签、标记已读）
7. **Error path**：单邮件异常被 catch，`LocalStore.record_error(message_id, error_message)`，继续下一封

---

## 4. 核心数据契约

### Gist（schemas.py）
- LLM 必出：title, summary, score, tags, key_insights, mentioned_links, is_spam_or_irrelevant
-  ingestion 填充：original_id, sender, sender_email, received_at, raw_markdown, original_url；发布后：notion_page_id, local_file_path
- `is_valuable(min_score)`：非 spam 且 score >= min_score

### RawEmail（schemas.py）
- message_id, subject, sender, date, html_content, text_content, labels, urls；`content` 属性优先 HTML

### LocalStore 表
- **processed_emails**：message_id, subject, sender, processed_at, score, is_spam, notion_page_id
- **processing_errors**：message_id, error_message, error_time
- **prompt_history**：id, prompt_type, content, created_at, created_by

---

## 5. 配置要点（settings.py）

- **必填**：GMAIL_USER, GMAIL_APP_PASSWORD, OPENAI_API_KEY, NOTION_API_KEY, NOTION_DATABASE_ID
- **常用**：TARGET_LABEL, OPENAI_BASE_URL, LLM_MODEL_NAME, CHECK_INTERVAL_MINUTES, MIN_VALUE_SCORE
- **Prompt**：PROMPT_SYSTEM_PATH, PROMPT_USER_PATH（默认 prompts 目录）
- **Web**：WEB_SERVER_HOST, WEB_SERVER_PORT（默认 0.0.0.0:5800）
- **ensure_env_file()**：无 .env 时从 .env.example 创建（多路径查找），Docker 下无写权限则静默跳过

---

## 6. Web API（api.py）

| 路由 | 方法 | 说明 |
|------|------|------|
| /api/health | GET | 健康检查 |
| /api/config | GET/POST | 配置读取（脱敏）/ 写入 .env |
| /api/prompts | GET/POST | 当前 Prompt / 保存并重载 |
| /api/prompts/reload | POST | 仅重载 Prompt |
| /api/prompts/test | POST | 用示例内容测 LLM 输出 |
| /api/prompts/history | GET | Prompt 历史 |
| /api/prompts/restore | POST | 按 version_id 恢复 |
| /api/tasks/status | GET | 调度器状态 |
| /api/tasks/run | POST | 手动执行 run_once() |
| /api/tasks/history | GET | 处理历史（LocalStore） |
| /api/tasks/errors | GET | 失败任务列表 |
| /api/tasks/retry | POST | 删除错误记录以便重试 |
| /api/stats | GET | 统计：total_processed, total_spam, avg_score, total_errors |
| / | GET | 静态 index.html |

- 使用 `app.config["pipeline"]` 与 `app.config["local_store"]`；LocalStore 使用线程本地 SQLite 连接，避免跨线程错误。

---

## 7. 运行与测试

- **本地**：`python main.py`（定时 + Web）、`python main.py --once`（单次）
- **Docker**：`docker-compose up -d`，Web 在 5800，数据在 ./data、./logs、./prompts
- **测试**：  
  - `tests/test_config.py` 验证配置  
  - `tests/test_ingestion.py` Gmail  
  - `tests/test_llm_engine.py` LLM  
  - `tests/test_publisher.py` Notion  
  - `tests/check_notion_db.py` 检查 Notion 属性是否与代码一致

---

## 8. 开发时注意点

1. **Notion**：属性名与类型必须与 `publisher.py` 中映射一致（Name/Title, Score/Number, Tags/Multi-select, Summary/Rich text, Date, Sender/Select, Link/URL 等）。
2. **Prompt**：优先改 `prompts/*.txt` 或通过 Web 编辑；LLM 输出需严格符合 `Gist`，否则需在 llm_engine 中做兼容或校验。
3. **错误与重试**：单邮件失败只记录 errors 并 continue；外部 API 用 tenacity；数据库用线程本地连接。
4. **新增依赖**：改 requirements.txt 并考虑 Docker 构建与镜像源。
5. **文档**：用户向内容集中在 `docs/GUIDE.md`；规范与设计在 `docs/spec/`。

---

## 9. 文档索引

| 文档 | 用途 |
|------|------|
| README.md | 项目介绍、快速开始、配置要点 |
| docs/GUIDE.md | 完整使用、Docker、Notion、Web、故障排查 |
| docs/README.md | 文档导航 |
| docs/spec/MANIFESTO.md | 宪章、边界、路线图 |
| docs/spec/AI_GUIDELINES.md | 编码与架构约束 |
| docs/spec/prd.md | 用户故事、数据实体 |
| docs/spec/tech_init.md | 数据契约、Notion Schema、Prompt |
| docs/spec/tech_process.md | 各组件接口规格 |
| docs/spec/.do.md | 分步实施顺序 |

---

开发前建议：先跑通 `docker-compose up` 与 Web（http://localhost:5800），再按 spec 与本文修改或扩展功能。
