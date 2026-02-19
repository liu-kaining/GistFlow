# GistFlow

> 让信息像水一样流动，但只把金沙（Gist）留在你的知识库里

**GistFlow** 是一个自动化的 ETL 管道系统，从 Gmail 提取 Newsletter，通过 LLM 进行深度清洗、总结、评分，最终沉淀为 Notion 数据库中的结构化知识资产。

---

## 为什么需要 GistFlow？

### 🎯 解决的痛点

| 痛点 | 描述 | GistFlow 的解法 |
|------|------|-----------------|
| **推拉失衡** | 邮箱是 Push 模式，好内容与垃圾混杂，稍纵即逝 | 自动过滤、评分，只保留高价值内容 |
| **FOMO 焦虑** | 订阅了 50+ 源，全读累死，不读焦虑 | AI 代读，只看 Notion 摘要即可 |
| **资产为零** | 即使读了，也是过眼云烟，一个月后找不到 | 自动入库 Notion，可搜索、可追溯 |

### 💡 核心价值

- **释放大脑带宽** - 把"筛选"交给 AI，把"思考"留给自己
- **构建知识复利** - 每周自动新增 20-50 条高质量技术情报
- **成为信息策展人** - 你的 Prompt 越懂你，筛选出的信息越有价值

---

## ✨ 核心功能

### 智能邮件获取
- 🔍 **标签过滤** - 只处理带 `Newsletter` / `news` 标签的邮件
- 🔒 **隐私保护** - 私人邮件不会被处理
- ♻️ **去重机制** - SQLite 记录已处理邮件，避免重复

### AI 深度处理
- 📝 **智能摘要** - 100 字以内的 TL;DR
- 📊 **价值评分** - 0-100 分，自动过滤低价值内容
- 🏷️ **自动标签** - 提取 2-5 个分类标签（AI、Dev、Finance 等）
- 💡 **核心洞察** - 提取 3-5 个关键信息点
- 🔗 **链接提取** - 自动识别文中的工具、仓库、文章链接

### 双模式存储
- 📚 **Notion 数据库** - 结构化存储，可搜索、可协作
- 📄 **本地文件** - Markdown / JSON 格式，离线可用

### 运维友好
- 🐳 **Docker 支持** - 一键部署，国内镜像源
- 🌐 **Web 管理界面** - 在线配置、Prompt 调整、手动触发
- 📈 **处理统计** - API 查询运行状态和统计信息

---

## 🏗️ 技术架构

### 数据流管道

```
Gmail Newsletter
      ↓
  [Ingestion] → IMAP 获取带标签邮件
      ↓
  [Cleaner] → HTML 转 Markdown，去噪截断
      ↓
  [LLM Engine] → AI 提取摘要、评分、标签
      ↓
  [Publisher] → 双发布 (Notion + Local)
      ↓
  [Archive] → 移除标签，标记已处理
```

### 技术栈

| 层级 | 技术选型 |
|------|----------|
| **邮箱获取** | `imap-tools` |
| **HTML 处理** | `beautifulsoup4` + `markdownify` |
| **LLM 编排** | `langchain` + `langchain-openai` |
| **数据验证** | `pydantic` V2 |
| **Notion API** | `notion-client` |
| **调度** | `apscheduler` |
| **日志** | `loguru` |
| **Web** | `flask` |
| **重试** | `tenacity` |
| **时区** | UTC+8 (东八区) |

### 项目结构

```
GistFlow/
├── gistflow/                # 主代码包
│   ├── config/              # Pydantic 配置管理
│   ├── core/                # 核心业务逻辑
│   │   ├── ingestion.py     # Gmail IMAP 邮件获取
│   │   ├── cleaner.py       # HTML→Markdown 清洗
│   │   ├── llm_engine.py    # LLM 智能提取
│   │   ├── publisher.py     # Notion 发布
│   │   └── local_publisher.py  # 本地文件存储
│   ├── database/            # SQLite 去重存储
│   ├── models/              # Pydantic 数据模型
│   ├── utils/               # 日志等工具
│   └── web/                 # Flask REST API + Web UI
├── prompts/                 # Prompt 模板文件（可挂载编辑）
├── tests/                   # 测试文件
├── docs/                    # 完整文档
│   ├── GUIDE.md            # 使用指南
│   ├── DEV_READINESS.md     # 开发准备摘要
│   ├── PROJECT_STRUCTURE.md # 项目结构说明
│   └── spec/                # 项目规范文档
├── main.py                  # 主程序入口
├── Dockerfile               # Docker 镜像（国内镜像源）
├── docker-compose.yml       # 容器编排
├── requirements.txt         # Python 依赖
└── .env.example            # 配置模板
```

> 📖 详细结构说明请查看 [docs/PROJECT_STRUCTURE.md](./docs/PROJECT_STRUCTURE.md)

---

## 🚀 快速开始

### 1. 环境准备

```bash
# 克隆项目
git clone <repository-url>
cd GistFlow

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# 或 .venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置

```bash
# 复制配置模板
cp .env.example .env

# 编辑 .env 文件，填入你的配置
# 必填项：
# - GMAIL_USER: Gmail 邮箱
# - GMAIL_APP_PASSWORD: Gmail 应用专用密码
# - OPENAI_API_KEY: LLM API 密钥
# - OPENAI_BASE_URL: API 地址（支持 OpenAI/DeepSeek/OneAPI 等）
```

### 3. 运行

```bash
# 单次运行（处理邮件后退出）
python main.py --once

# 定时运行（每30分钟自动处理）
python main.py

# Docker 运行（推荐）
docker-compose up -d
```

> 💡 **提示**：推荐使用 Docker 运行，详细指南请查看 [docs/GUIDE.md](./docs/GUIDE.md)

---

## ⚙️ 配置说明

### Gmail 标签匹配

GistFlow 只处理带特定标签的邮件，**私人邮件不会被处理**。

标签匹配**不区分大小写**，自动识别以下变体：

| 匹配规则 | 示例 |
|----------|------|
| Newsletter | `Newsletter`、`newsletter`、`NEWSLETTER` |
| News | `News`、`news`、`NEWS` |
| Newsletters | `Newsletters`、`newsletters` |

### Notion 数据库配置

创建数据库时需要以下属性：

| 属性名 | 类型 | 说明 |
|--------|------|------|
| Name | Title | 邮件标题 |
| Score | Number | 价值评分 (0-100) |
| Summary | Text | 摘要 |
| Tags | Multi-select | 分类标签 |
| Sender | Select | 发件人 |
| Date | Date | 接收日期 |
| Link | URL | 原始链接 |

### 本地存储（可选）

```bash
# .env 配置
ENABLE_LOCAL_STORAGE=true       # 启用本地存储
LOCAL_STORAGE_PATH=./gists      # 存储目录
LOCAL_STORAGE_FORMAT=markdown   # 格式：markdown 或 json
```

### 评分阈值配置

```bash
# 价值评分阈值（0-100），低于此分数的内容会被跳过
MIN_VALUE_SCORE=30
```

### 批量处理配置

```bash
# 单次运行最多处理的邮件数量（默认 50，最大 100）
MAX_EMAILS_PER_RUN=50
```

系统会先统计所有未处理邮件总数，然后按此限制分批处理。在 Web 界面中会显示：
- **邮件总数**：所有待处理的邮件数量
- **本次处理**：本次实际处理的邮件数
- **剩余邮件**：等待下次运行处理的邮件数

---

## 📊 开发进度

### ✅ 全部完成

| 模块 | 状态 | 功能 |
|------|------|------|
| 基础设施 | ✅ | 项目结构、配置管理、日志工具 |
| 邮件获取 | ✅ | IMAP 连接、标签过滤、去重存储、批量处理（最多 50 封/次） |
| 内容清洗 | ✅ | HTML→Markdown、去噪、截断策略 |
| LLM 提取 | ✅ | 多模型支持、结构化输出、Fallback、重试机制 |
| Notion 发布 | ✅ | 页面创建、属性映射、分块上传、5 次重试 |
| 本地存储 | ✅ | Markdown/JSON 双格式 |
| Web API | ✅ | Flask 管理界面、任务历史、分页搜索 |
| Docker | ✅ | 多阶段构建、国内镜像源 |

### 代码质量

- ✅ 所有函数包含类型注解
- ✅ 使用 Google Style Docstrings
- ✅ 具体异常捕获
- ✅ tenacity 重试机制（Notion: 5 次，LLM: 3 次）
- ✅ 无 `print()` 语句
- ✅ 统一时区处理（UTC+8）

### 🆕 最新更新

#### 批量处理优化（2025-02-17）
- ✨ **提升处理上限**：单次运行最多处理 50 封邮件（默认值，可配置至 100）
- 📊 **总量统计**：先统计所有未处理邮件总数，再按限制分批处理
- 🎯 **进度可视化**：Web 界面显示邮件总数、本次处理数和剩余数量
- 🔄 **重试机制增强**：
  - Notion API：5 次重试，指数退避（2s → 4s → 8s → 16s → 30s）
  - LLM API：3 次重试，指数退避（4s → 4s → 10s）
  - 关键内容块失败会抛出异常，确保页面完整性

---

## 📚 文档

| 文档 | 说明 |
|------|------|
| [docs/GUIDE.md](./docs/GUIDE.md) | 完整使用指南 |
| [docs/CODE_REVIEW.md](./docs/CODE_REVIEW.md) | 代码审查报告 |
| [docs/spec/MANIFESTO.md](./docs/spec/MANIFESTO.md) | 项目宪章 |
| [docs/spec/AI_GUIDELINES.md](./docs/spec/AI_GUIDELINES.md) | AI 编码规范 |

---

## 🐛 问题排查

遇到问题？查看 [Docker 问题排查指南](./docs/DOCKER_TROUBLESHOOTING.md)

---

## 📄 License

MIT License