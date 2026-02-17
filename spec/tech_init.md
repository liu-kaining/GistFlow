# 🚀 GistFlow - 详细设计与实施手册 (Part 3 & 4)

## Phase 3: 详细设计 (Module Design)

这一阶段定义了系统内部的“契约”：数据结构、数据库 Schema 和 AI 的思考逻辑。

### 3.1 数据契约 (The Contract: Pydantic Models)

这是系统内流转的唯一标准数据格式。所有模块（Gmail读取、LLM输出、Notion写入）必须严格遵守此结构。

```python
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

class Gist(BaseModel):
    """
    Gist 是从邮件中提取出的核心知识单元。
    LLM 必须输出符合此结构的 JSON。
    """
    title: str = Field(..., description="邮件的原标题，或者由 AI 优化的更清晰的标题")
    summary: str = Field(..., description="100字以内的核心摘要 (TL;DR)")
    score: int = Field(..., description="价值打分 (0-100)，基于信息密度和相关性")
    tags: List[str] = Field(default_factory=list, description="自动提取的分类标签，如 AI, Dev, Finance")
    key_insights: List[str] = Field(default_factory=list, description="3-5个核心洞察点")
    mentioned_links: List[str] = Field(default_factory=list, description="文中提及的重要链接/工具/仓库")
    is_spam_or_irrelevant: bool = Field(False, description="如果是纯广告、收据或无意义内容，标记为 True")
    
    # 以下字段由 Ingestion 层填充，LLM 不需要生成
    original_id: Optional[str] = None
    sender: Optional[str] = None
    received_at: Optional[datetime] = None
    raw_markdown: Optional[str] = None
    original_url: Optional[str] = None

```

### 3.2 Notion 数据库 Schema (Manual Setup)

在写代码前，你需要手动在 Notion 创建一个 Database，并确保 **Property Name (属性名)** 和 **Type (类型)** 严格一致：

| Property Name | Type | 说明 |
| --- | --- | --- |
| **Name** | Title | 对应 `Gist.title` |
| **Score** | Number | 对应 `Gist.score` (设为 Bar 或 Ring 显示更直观) |
| **Tags** | Multi-select | 对应 `Gist.tags` |
| **Summary** | Rich text | 对应 `Gist.summary` |
| **Date** | Date | 对应 `Gist.received_at` |
| **Sender** | Select | 对应 `Gist.sender` |
| **Link** | URL | 对应 `Gist.original_url` (如有) |
| **Status** | Status | 默认 "Unread", 可选 "Read", "Archived" |

### 3.3 核心 Prompt 设计 (The Brain)

这是给 LLM 的指令。我们在代码中将使用 `System Message` + `User Message` 的结构。

**System Prompt (角色设定):**

```text
You are an expert Tech Information Analyst. Your goal is to process incoming emails (newsletters, technical updates, blogs) and extract high-value knowledge.

Input: Raw email content (Markdown format).
Output: A valid JSON object strictly following the `Gist` schema.

Rules:
1.  **Filtering**: If the email is a receipt, pure marketing spam, verification code, or extremely low value, set `is_spam_or_irrelevant` to true.
2.  **Scoring**: Score from 0-100. 
    - >80: High density technical deep dives, tutorials, breaking news.
    - 40-60: General updates, weekly links without context.
    - <30: Marketing fluff.
3.  **Language**: Summarize and extract insights in **Chinese (Simplified)**, unless the content is strictly code or proper nouns.
4.  **Formatting**: Keep `key_insights` concise (bullet points style).

```

**User Prompt (任务指令):**

```text
Here is the email content:
---
{email_markdown_content}
---

Extract the gist now. Output strictly JSON.

```

---

## Phase 4: 开发实施手册 (Dev Guide)

### 4.1 给 Cursor/Claude 的“系统级指令” (.cursorrules)

在你开始写代码前，把这段话复制给 AI，作为项目的全局规则。

```markdown
# Project Rules for GistFlow

1.  **Architecture**: 
    - Python 3.11+, Dockerized.
    - Modular design: `core/ingestion`, `core/llm`, `core/notion`.
    - Use `pydantic-settings` for config management.

2.  **Libraries**:
    - `imap-tools` for Gmail.
    - `langchain` + `langchain-openai` (or compatible) for LLM.
    - `notion-client` for Notion API.
    - `loguru` for logging.

3.  **Error Handling**:
    - Never crash the main loop. Catch errors in processing individual emails, log them, and move to the next.
    - Use `backoff` decorators for API calls (Notion/LLM).

4.  **Style**:
    - Type hints are mandatory.
    - Use `pathlib` for file paths.
    - Use standard `if __name__ == "__main__":` entry points for testing modules independently.

```

### 4.2 分步开发计划 (Step-by-Step Implementation)

不要试图一次性生成所有代码。让 Cursor 按照以下顺序，一个模块一个模块地写，写完一个验证一个。

#### Step 1: 基础设施搭建 (Infrastructure)

* **指令**: "Create the project structure, `pyproject.toml` (using poetry or pip), and `config/settings.py` to load `.env` variables (GMAIL_USER, GMAIL_APP_PASSWORD, OPENAI_API_KEY, NOTION_TOKEN)."
* **验证**: 运行代码能成功打印出加载的环境变量。

#### Step 2: 邮件获取模块 (Ingestion)

* **指令**: "Implement `core/ingestion.py`. Use `imap-tools`. Create a function `fetch_unprocessed_emails(limit=5)` that connects to Gmail, searches for `label:Newsletter`, and returns a list of email objects. Also implement a simple `HTML -> Text` converter using `beautifulsoup4`."
* **验证**: 运行脚本，能打印出你邮箱里最近 5 封 Newsletter 的标题和纯文本内容。

#### Step 3: LLM 智能提取模块 (The Brain)

* **指令**: "Implement `core/llm_engine.py`. defined the `Gist` Pydantic model. Create a function `analyze_email(text: str) -> Gist` using LangChain. Use `with_structured_output` (function calling) to force JSON output."
* **验证**: 手动传入一段文本（比如把刚才抓到的邮件内容复制进去），看能否吐出完美的 JSON 数据。

#### Step 4: Notion 写入模块 (Publisher)

* **指令**: "Implement `core/notion_publisher.py`. Create a function `push_to_notion(gist: Gist)`. Map the Pydantic fields to Notion Block properties. Handle the creation of the page and appending the detailed content as blocks."
* **验证**: 运行脚本，检查你的 Notion 数据库是否新增了一条记录。

#### Step 5: 主循环与 Docker (Main Loop)

* **指令**: "Create `main.py` using `apscheduler` to run the job every 30 minutes. Handle graceful shutdowns. Create `Dockerfile` and `docker-compose.yml`."
* **验证**: 本地 `docker-compose up`，观察日志，确认流程自动化跑通。