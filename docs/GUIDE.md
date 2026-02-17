# GistFlow 完整使用指南

## 📋 目录

- [快速开始](#快速开始)
- [Docker 运行](#docker-运行)
- [Notion 配置](#notion-配置)
- [Web 管理界面](#web-管理界面)
- [故障排查](#故障排查)
- [常见问题](#常见问题)

---

## 🚀 快速开始

### 前置要求

1. 已安装 Docker 和 Docker Compose
2. 已配置 `.env` 文件（包含所有必需的配置项）
3. Gmail App Password（用于 IMAP 访问）
4. Notion Integration Token 和 Database ID

### 1. 构建并启动

```bash
# 构建 Docker 镜像
docker-compose build

# 启动服务（后台运行）
docker-compose up -d

# 查看日志
docker-compose logs -f
```

> 💡 **提示**：Dockerfile 已配置使用国内镜像源（DaoCloud 和清华大学 PyPI 镜像），适合国内环境使用。

### 2. 验证配置

```bash
# 验证配置是否正确加载
docker-compose run --rm gistflow python tests/test_config.py

# 测试 Notion 连接
docker-compose run --rm gistflow python tests/test_publisher.py

# 测试 Gmail 连接
docker-compose run --rm gistflow python tests/test_ingestion.py

# 测试 LLM 连接
docker-compose run --rm gistflow python tests/test_llm_engine.py
```

### 3. 手动触发一次处理（测试）

```bash
# 单次运行（处理邮件后退出）
docker-compose run --rm gistflow python main.py --once
```

这会：
1. 连接 Gmail，查找带 `Newsletter` 标签的未读邮件
2. 使用 LLM 处理邮件内容
3. 将结果保存到 Notion 和/或本地文件
4. 标记邮件为已处理

### 4. 检查处理结果

- **Notion 数据库**：打开你的 Notion 数据库页面，应该能看到新创建的页面
- **本地存储**（如果启用）：查看 `./data/gists/` 目录
- **数据库记录**：进入容器查看 SQLite 数据库

```bash
docker-compose exec gistflow /bin/bash
sqlite3 /app/data/gistflow.db "SELECT * FROM processed_emails ORDER BY processed_at DESC LIMIT 10;"
```

---

## 🐳 Docker 运行

### 常用命令

```bash
# 查看容器状态
docker-compose ps

# 查看实时日志
docker-compose logs -f

# 查看最近 100 行日志
docker-compose logs --tail=100

# 进入容器调试
docker-compose exec gistflow /bin/bash

# 重启服务
docker-compose restart

# 停止服务
docker-compose down

# 停止并删除容器和数据卷
docker-compose down -v
```

### 数据持久化

Docker Compose 配置中已经设置了数据卷挂载：

- `./data:/app/data` - SQLite 数据库文件
- `./logs:/app/logs` - 日志文件
- `./prompts:/app/prompts` - Prompt 文件（可在宿主机编辑）

这些目录会在项目根目录下自动创建，数据会持久化保存。

### 运行模式

#### 定时运行模式（默认）
- 容器启动后，每 30 分钟自动检查一次新邮件
- 适合长期运行，自动处理

#### 单次运行模式
- 运行一次后退出
- 适合测试和手动触发

### 健康检查

容器包含健康检查功能，可以通过以下命令查看：

```bash
docker-compose ps
```

健康检查会每 5 分钟运行一次，验证配置是否正确加载。

### 重新构建镜像（代码更新后）

```bash
docker-compose build --no-cache
docker-compose up -d
```

---

## 📝 Notion 配置

### 问题诊断

如果遇到错误：`Name is not a property that exists`，说明数据库属性名称不匹配。

### 快速检查数据库属性

运行以下命令查看数据库的实际属性：

```bash
docker-compose run --rm gistflow python tests/check_notion_db.py
```

这会显示：
- 数据库中实际存在的属性名称和类型
- 代码期望的属性名称和类型
- 哪些属性匹配，哪些不匹配

### 正确的数据库配置

#### 必需属性（必须完全匹配）

| 属性名称 | 类型 | 说明 | 是否必需 |
|---------|------|------|---------|
| **Name** | Title | 邮件标题 | ✅ 必需 |
| **Score** | Number | 价值评分 (0-100) | ✅ 必需 |
| **Summary** | Text | 摘要 | ✅ 必需 |
| **Tags** | Multi-select | 分类标签 | ✅ 必需 |
| **Sender** | Select | 发件人 | ⚠️ 可选 |
| **Date** | Date | 接收日期 | ⚠️ 可选 |
| **Link** | URL | 原始链接 | ⚠️ 可选 |

⚠️ **属性名称必须完全匹配**（区分大小写）：
- ✅ 正确：`Name`、`Score`、`Summary`、`Tags`
- ❌ 错误：`name`、`SCORE`、`summary`、`TAGS`、`标签`

### 配置步骤

#### 方法 1：创建新数据库（推荐）

1. **创建新数据库**
   - 在 Notion 中点击 `+ New` → `Database` → `New database`
   - 选择 `Table` 视图

2. **添加必需属性**
   - 点击 `+` 添加新属性
   - 按照上表添加所有必需属性

3. **获取数据库 ID**
   - 打开数据库页面
   - 复制 URL，格式：`https://www.notion.so/your-workspace/DATABASE_ID?v=...`
   - 提取 `DATABASE_ID`（32个字符，去掉连字符）
   - 更新 `.env` 中的 `NOTION_DATABASE_ID`

4. **分享给 Integration**
   - 点击数据库右上角的 `...` → `Connections`
   - 添加你的 Notion Integration
   - 确保有 `Full access` 权限

#### 方法 2：修改现有数据库

如果已有数据库但属性名称不匹配：

1. **重命名属性**
   - 点击属性列的 `...` 菜单
   - 选择 `Rename`
   - 重命名为代码期望的名称（区分大小写）

2. **修改属性类型**
   - 点击属性列的 `...` 菜单
   - 选择 `Edit property`
   - 修改为正确的类型

3. **验证配置**
   ```bash
   docker-compose run --rm gistflow python tests/check_notion_db.py
   ```

### 验证配置

运行检查脚本：

```bash
docker-compose run --rm gistflow python tests/check_notion_db.py
```

应该看到所有属性都显示 ✅。

### 测试发布

配置完成后，测试发布功能：

```bash
docker-compose run --rm gistflow python tests/test_publisher.py
```

如果看到 `✅ Successfully published to Notion!`，说明配置成功！

---

## 🌐 Web 管理界面

### 访问地址

启动服务后，可以通过以下地址访问 Web 管理界面：

```
http://localhost:5800
```

### 功能说明

#### 1. 仪表盘
- 查看任务运行状态
- 查看统计信息（已处理邮件数、平均评分等）
- 快速操作（手动执行任务、刷新统计）

#### 2. Prompt 管理（核心功能）
- **编辑 Prompt**：修改 System Prompt 和 User Prompt Template
- **保存并重载**：保存 Prompt 到文件并立即生效
- **测试 Prompt**：输入示例内容，查看 LLM 输出效果
- **Prompt 历史**：查看和恢复历史版本

#### 3. 配置管理
- 查看当前配置（敏感信息已脱敏）
- 修改配置项（保存到 `.env` 文件）

#### 4. 任务管理
- 查看处理历史记录
- 查看失败任务列表
- 重试失败的任务

### Prompt 管理使用指南

1. **编辑 Prompt**
   - 在 "Prompt 管理" 页面编辑 System Prompt 和 User Prompt Template
   - 点击 "加载当前 Prompt" 查看现有内容

2. **保存 Prompt**
   - 编辑完成后，点击 "保存并重载"
   - Prompt 会保存到 `prompts/` 目录，并立即生效

3. **测试 Prompt**
   - 在测试区域输入示例邮件内容
   - 点击 "测试" 查看 LLM 输出
   - 可以测试不同的 Prompt 效果

4. **Prompt 历史**
   - 每次保存 Prompt 都会记录历史版本
   - 可以查看和恢复历史版本

---

## 🔧 故障排查

### Docker 构建问题

#### 问题：无法拉取 Docker 镜像

**错误信息**：
```
failed to solve: python:3.11-slim: failed to resolve source metadata
```

**解决方案**：

Dockerfile 已默认配置使用国内镜像源，如果仍然失败：

1. **配置 Docker 镜像加速器**
   - 打开 Docker Desktop → Settings → Docker Engine
   - 添加以下配置：
   ```json
   {
     "registry-mirrors": [
       "https://docker.mirrors.ustc.edu.cn",
       "https://hub-mirror.c.163.com",
       "https://mirror.baidubce.com"
     ]
   }
   ```
   - 点击 "Apply & Restart"

2. **清理并重新构建**
   ```bash
   # 清理 Docker 缓存
   docker system prune -a
   
   # 重新构建（不使用缓存）
   docker-compose build --no-cache --pull
   ```

### Notion 配置问题

#### 错误：`Name is not a property that exists`

**原因**：数据库中没有名为 `Name` 的属性

**解决**：
1. 运行 `docker-compose run --rm gistflow python tests/check_notion_db.py` 查看实际属性名称
2. 重命名数据库属性为 `Name`（区分大小写）

#### 错误：`Property type mismatch`

**原因**：属性类型不匹配（例如 `Score` 应该是 `Number` 但实际是 `Text`）

**解决**：
1. 修改属性类型为正确的类型
2. 参考上表的类型要求

#### 错误：`Database not found`

**原因**：数据库 ID 错误或 Integration 没有权限

**解决**：
1. 检查 `.env` 中的 `NOTION_DATABASE_ID` 是否正确
2. 确保 Integration 已分享给数据库
3. 检查 Integration 权限是否为 `Full access`

### 容器运行问题

#### 查看容器日志

```bash
docker-compose logs gistflow
```

#### 检查配置是否正确加载

```bash
docker-compose run --rm gistflow python tests/test_config.py
```

#### 检查环境变量

```bash
docker-compose run --rm gistflow env | grep -E "(GMAIL|OPENAI|NOTION)"
```

#### 进入容器调试

```bash
docker-compose exec gistflow /bin/bash
```

### 清理残留容器和网络

```bash
# 停止并删除所有 gistflow 容器
docker-compose down

# 强制删除所有相关容器
docker rm -f $(docker ps -aq --filter "name=gistflow") 2>/dev/null || true

# 删除网络（如果还有残留）
docker network rm gistflow_gistflow_network 2>/dev/null || true

# 完全清理（包括镜像）
docker rmi gistflow:latest 2>/dev/null || true
docker system prune -f
```

---

## ❓ 常见问题

### Docker 相关

**Q: 容器无法启动？**

A: 检查日志：`docker-compose logs gistflow`，常见原因：
- 配置错误（检查 `.env` 文件）
- 端口被占用（检查 5800 端口）
- 权限问题（确保 Docker 有权限访问项目目录）

**Q: 如何更新代码后重新部署？**

A:
```bash
docker-compose build --no-cache
docker-compose up -d
```

**Q: 如何查看容器资源使用情况？**

A: `docker stats gistflow_agent`

### Notion 相关

**Q: 属性名称必须完全匹配吗？**

A: 是的，**必须完全匹配**（区分大小写）。`Name` 和 `name` 是不同的。

**Q: 可以添加其他属性吗？**

A: 可以！代码只会使用上述属性，其他属性不会影响功能。

**Q: 属性顺序重要吗？**

A: 不重要，只要属性名称和类型正确即可。

**Q: Tags 属性可以添加预设值吗？**

A: 可以，但不影响功能。代码会自动创建新的标签值。

### 运行相关

**Q: 如何修改检查邮件的频率？**

A: 修改 `.env` 中的 `CHECK_INTERVAL_MINUTES`（单位：分钟）

**Q: 如何只处理一次邮件就退出？**

A: `docker-compose run --rm gistflow python main.py --once`

**Q: 如何查看处理历史？**

A: 通过 Web 界面（http://localhost:5800）的"任务"页面，或进入容器查看数据库

**Q: Web 界面无法访问？**

A: 
1. 检查容器是否运行：`docker-compose ps`
2. 检查端口映射：确保 `5800:5800` 已配置
3. 检查防火墙设置
4. 查看日志：`docker-compose logs gistflow`

### Prompt 相关

**Q: 如何修改 Prompt？**

A: 通过 Web 界面（http://localhost:5800）的"Prompt 管理"页面，或直接编辑 `prompts/` 目录下的文件

**Q: 修改 Prompt 后如何生效？**

A: 在 Web 界面点击"重新加载"，或重启容器

**Q: 如何测试 Prompt 效果？**

A: 在 Web 界面的"Prompt 管理"页面，使用"测试 Prompt"功能

---

## 📚 下一步

- 确保 Gmail 中有带 `Newsletter` 标签的邮件
- 等待第一次自动处理（或手动触发一次）
- 检查 Notion 数据库是否有新记录
- 根据需要调整 `.env` 中的配置
- 通过 Web 界面优化 Prompt，提升处理质量

---

## 📖 相关文档

- [项目 README](../README.md) - 项目概述和快速开始
- [项目规范文档](./spec/) - 技术规范和设计文档
