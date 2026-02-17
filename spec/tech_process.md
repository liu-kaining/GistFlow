# 🚀 GistFlow - 详细实施规格说明书 (Part 5 & 6)

## Phase 5: 核心模块接口规范 (Component Specifications)

这一部分是给 AI 的具体编码蓝图。请要求 Cursor 严格遵循这些 Class 和 Method 签名。

### 5.1 配置管理 (`config/settings.py`)

使用 `pydantic-settings` 来管理环境变量，确保类型安全。

```python
# spec: config/settings.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Gmail Config
    GMAIL_USER: str
    GMAIL_APP_PASSWORD: str
    GMAIL_FOLDER: str = "INBOX"  # 或者 "[Gmail]/All Mail"
    TARGET_LABEL: str = "Newsletter" # 只处理带有此标签的邮件

    # LLM Config
    OPENAI_API_KEY: str
    OPENAI_BASE_URL: str = "https://api.openai.com/v1" # 方便切换 OneAPI
    LLM_MODEL_NAME: str = "gpt-4o" # 或 "gemini-1.5-pro"

    # Notion Config
    NOTION_API_KEY: str
    NOTION_DATABASE_ID: str

    # System Config
    LOG_LEVEL: str = "INFO"
    CHECK_INTERVAL_MINUTES: int = 30
    MAX_EMAILS_PER_RUN: int = 10 # 每次运行最多处理几封，防止超限

    class Config:
        env_file = ".env"

```

### 5.2 邮件获取器 (`core/ingestion.py`)

负责连接 IMAP，搜索邮件，并做初步的清洗。

**Class Design:**

```python
class EmailFetcher:
    def __init__(self, settings: Settings):
        ...

    def connect(self):
        """建立 IMAP 连接"""
        ...

    def fetch_unprocessed(self, limit: int = 10) -> List[RawEmail]:
        """
        1. 搜索 Label = settings.TARGET_LABEL
        2. 过滤掉已经在 SQLite 中存在的 Message-ID
        3. 返回 RawEmail 对象列表
        """
        ...
        
    def mark_as_processed(self, email_id: str):
        """
        处理成功后调用：
        1. 移除 'Newsletter' 标签
        2. 添加 'GistFlow-Processed' 标签 (如果不存在则创建)
        """
        ...

```

### 5.3 内容清洗器 (`core/cleaner.py`)

**关键逻辑：**
这是最容易出问题的地方。LLM 的 Context Window 是有限的，而且邮件 HTML 包含大量追踪代码。

**功能规范：**

1. **HTML to Markdown**: 使用 `markdownify` 库，配置 `strip=['a', 'img']` (可选，根据需要保留图片链接)。
2. **Noise Removal**: 去除 `unsubscribe`、`view in browser`、`copyright` 等页脚信息。
3. **Truncation (截断策略)**:
* 如果清洗后的 Markdown 字符数 > 20,000 (约 5k tokens)，则进行截断。
* 保留前 15,000 字符 + "..." + 后 2,000 字符 (通常结论在最后)。
* 或者直接截断并添加标记 `[Content Truncated for AI Processing]`。



### 5.4 智能引擎 (`core/llm_engine.py`)

负责与 LLM 交互，强制输出 JSON。

**Class Design:**

```python
class GistEngine:
    def __init__(self, settings: Settings):
        # 初始化 LangChain ChatOpenAI
        ...

    def extract_gist(self, raw_text: str) -> Gist:
        """
        Input: 清洗后的 Markdown 文本
        Output: Gist Pydantic 对象
        
        Logic:
        1. 构建 Prompt (System + User)。
        2. 调用 with_structured_output(Gist)。
        3. 捕获解析错误 (OutputParserException)，如果失败重试 1 次。
        """
        ...

```

### 5.5 Notion 发布器 (`core/publisher.py`)

负责将 `Gist` 对象映射为 Notion Block。

**Class Design:**

```python
class NotionPublisher:
    def __init__(self, settings: Settings):
        self.client = Client(auth=settings.NOTION_API_KEY)

    def push(self, gist: Gist):
        """
        1. create_page() 在 Database 中创建条目。
        2. 设置 Properties (Title, Score, Tags, Summary, URL)。
        3. 构建 Children Blocks:
           - Callout Block: 显示 Key Insights
           - Divider Block
           - Heading Block: "原文内容"
           - Toggle Block: 放入 gist.raw_markdown (防止刷屏)
        """
        ...

```

---

## Phase 6: 部署与运维文档 (Deployment)

### 6.1 环境变量模板 (`.env.example`)

```ini
GMAIL_USER=your_email@gmail.com
GMAIL_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
# 你的 Notion Database ID (从 URL 获取)
NOTION_DATABASE_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
NOTION_API_KEY=secret_xxxxxxxxxxxxxxxxxxxxxxxxxx

# LLM 配置 (支持 DeepSeek/Gemini/OpenAI)
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxx
OPENAI_BASE_URL=https://api.openai.com/v1
LLM_MODEL_NAME=gpt-4o

# 运行配置
CHECK_INTERVAL_MINUTES=60

```

### 6.2 Docker 构建文件 (`Dockerfile`)

```dockerfile
# 使用轻量级 Python 镜像
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 防止 Python 生成 pyc 文件
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 安装系统依赖 (如果有需要编译的库)
# RUN apt-get update && apt-get install -y gcc

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制源代码
COPY . .

# 启动命令 (直接运行 main.py)
CMD ["python", "main.py"]

```

### 6.3 编排文件 (`docker-compose.yml`)

```yaml
version: '3.8'

services:
  gistflow:
    build: .
    container_name: gistflow_agent
    restart: unless-stopped
    env_file:
      - .env
    volumes:
      - ./data:/app/data  # 挂载 SQLite 数据库，保证重启后去重记录不丢失
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"

```

**是否还有任何环节需要补充？** 如果没有，你可以把这些内容复制下来，开始你的 GistFlow 开发之旅了！