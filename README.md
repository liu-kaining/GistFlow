# GistFlow
让信息像水一样流动，但只把金沙（Gist）留在你的知识库里

## 快速开始

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
# 主要配置项：
# - GMAIL_USER: Gmail 邮箱
# - GMAIL_APP_PASSWORD: Gmail 应用专用密码
# - OPENAI_API_KEY: OpenAI API 密钥
# - NOTION_API_KEY: Notion 集成密钥
# - NOTION_DATABASE_ID: Notion 数据库 ID
```

### 3. 验证配置

```bash
# 配置验证
python tests/test_config.py

# 完整测试
python tests/test_pipeline.py
```

### 4. 运行

```bash
# 单次运行（处理邮件后退出）
python main.py --once

# 定时运行（每30分钟自动处理）
python main.py

# Docker 运行
docker-compose up -d
```

## 项目结构

```
GistFlow/
├── gistflow/
│   ├── config/         # 配置管理
│   │   └── settings.py
│   ├── core/           # 核心处理模块
│   │   ├── ingestion.py    # 邮件获取
│   │   ├── cleaner.py      # 内容清洗
│   │   ├── llm_engine.py   # LLM 智能提取
│   │   └── publisher.py    # Notion 发布
│   ├── database/       # 本地存储
│   │   └── local_store.py
│   ├── models/         # 数据模型
│   │   └── schemas.py
│   └── utils/          # 工具模块
│       └── logger.py
├── tests/              # 测试文件
│   ├── test_config.py
│   ├── test_ingestion.py
│   ├── test_llm_engine.py
│   ├── test_publisher.py
│   └── test_pipeline.py
├── main.py             # 主程序入口
├── Dockerfile          # Docker 镜像
├── docker-compose.yml  # 容器编排
├── pyproject.toml      # 项目配置
├── requirements.txt    # 依赖列表
└── .env.example        # 环境变量模板
```

## 数据流管道

```
Gmail Newsletter
      ↓
  [Ingestion] → 获取带标签邮件
      ↓
  [Cleaner] → HTML 转 Markdown，去噪
      ↓
  [LLM Engine] → AI 提取摘要、评分、标签
      ↓
  [Publisher] → 写入 Notion 数据库
      ↓
  [Archive] → 标记邮件已处理
```

## Gmail 标签匹配规则

**重要：GistFlow 只处理带特定标签的邮件，私人邮件不会被处理！**

### 标签匹配方式

标签匹配**不区分大小写**，自动识别以下变体：

| 匹配规则 | 示例 |
|----------|------|
| Newsletter | `Newsletter`、`newsletter`、`NEWSLETTER` |
| News | `News`、`news`、`NEWS` |
| Newsletters | `Newsletters`、`newsletters` |

### 使用方法

1. 在 Gmail 中创建标签（名称可以是 `Newsletter`、`news` 等任意变体）
2. 将订阅的邮件打上该标签
3. GistFlow 会自动识别并处理

### 隐私保护

- ✅ 只处理带标签的邮件
- ✅ 只处理未读邮件
- ✅ 私人邮件默认无标签，不会被处理
- ✅ 处理后自动移除标签，避免重复处理

## Notion 数据库配置

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

## 本地存储配置（可选）

除了 Notion，GistFlow 还支持将内容保存到本地文件，适合不需要云同步的用户。

### 配置项

```bash
# .env 文件配置
ENABLE_LOCAL_STORAGE=true          # 是否启用本地存储
LOCAL_STORAGE_PATH=./gists         # 存储目录
LOCAL_STORAGE_FORMAT=markdown      # 格式：markdown 或 json
```

### 存储格式

**Markdown 格式** - 适合人类阅读，带 YAML Front Matter：
```markdown
---
title: "文章标题"
score: 85
date: 2024-05-20T10:30:00
tags: ["AI", "Newsletter"]
sender: "Tech Weekly"
---

## Summary

这是文章摘要...

## Key Insights

- 洞察1
- 洞察2

## Links

- [相关链接](https://example.com)
```

**JSON 格式** - 适合程序处理：
```json
{
  "title": "文章标题",
  "summary": "摘要内容",
  "score": 85,
  "tags": ["AI", "Newsletter"],
  "key_insights": ["洞察1", "洞察2"],
  "metadata": {
    "sender": "Tech Weekly",
    "received_at": "2024-05-20T10:30:00"
  }
}
```

### 使用场景

| 配置 | 场景 |
|------|------|
| 只用 Notion | `ENABLE_LOCAL_STORAGE=false` |
| 只用本地 | 不配置 Notion API Key |
| 两者都用 | 默认配置（推荐） |

## 开发进度

### ✅ 全部完成！

| 步骤 | 模块 | 状态 | 说明 |
|------|------|------|------|
| Step 1 | 基础设施搭建 | ✅ 完成 | 项目结构、配置管理、日志工具 |
| Step 2 | 邮件获取模块 | ✅ 完成 | IMAP 连接、标签过滤、去重存储、内容清洗 |
| Step 3 | LLM 智能提取 | ✅ 完成 | LangChain 集成、结构化输出、重试机制、Fallback |
| Step 4 | Notion 写入 | ✅ 完成 | 页面创建、属性映射、内容块生成、重试机制 |
| Step 5 | 主循环与 Docker | ✅ 完成 | 调度器、优雅关闭、Docker 部署 |

### 代码质量

- [x] 所有函数包含类型注解
- [x] 使用 Google Style Docstrings
- [x] 具体异常捕获（无 `except Exception`）
- [x] tenacity 重试机制
- [x] 无 `print()` 语句（全部使用 logger）
- [x] 符合 AI_GUIDELINES.md 规范

### 完整性检查

```
✅ 模块导入测试通过
✅ 核心类方法完整
✅ 函数签名正确
✅ 数据模型完整
✅ 功能测试通过
```

**状态：代码完整，配置环境变量后即可运行！**
