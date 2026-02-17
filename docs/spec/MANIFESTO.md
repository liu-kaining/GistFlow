# 📜 GistFlow 项目宪章与战略白皮书

**版本：** 1.0
**日期：** 2026-02-17
**核心使命：** 将被动的信息洪流（Email），转化为主动的知识资产（Notion Knowledge Base）。

---

## 1. 核心问题定义 (The "Why")

我们解决的不是“阅读体验”问题，而是**“信息噪音”与“资产流失”**问题。

* **现状（Pain Point）：**
* **推拉失衡：** 邮箱是“推（Push）”模式，且是“流（Stream）”形态。好内容与垃圾混杂，稍纵即逝。
* **FOMO 焦虑：** 订阅了 50+ 个源，每天被迫在“全读完（累死）”和“全不读（焦虑）”之间挣扎。
* **资产为零：** 即使读了，也是过眼云烟。一个月后，你根本不记得哪封邮件里讲了那个关键的 AI 架构。


* **愿景（Vision）：**
* 建立一个 **“全天候数字分析师” (AI Agent)**。
* 它在我们睡觉时工作，在垃圾中淘金。
* 它不仅是“总结”，更是“清洗”和“结构化”。



---

## 2. 产品哲学与边界 (Philosophy & Boundaries)

为了不跑偏，我们需要明确**做什么**，更要明确**不做什么**。

### ✅ 我们做什么 (Core Scope)

1. **极度自私的过滤器：** 既然是 Self-Hosted，一切以“我（开发者）”的偏好为主。Prompt 不需要通用，只需要懂“我”。
2. **资产化优先：** 我们的终点不是“读完邮件”，而是“Notion 里多了一条永久笔记”。
3. **自动化 ETL：** Extract (IMAP) -> Transform (LLM Cleaning/Summarizing) -> Load (Notion)。

### ⛔ 我们绝对不做 (Anti-Goals / Out of Scope)

1. **不做通用邮件客户端：** 别想着用它回邮件、管附件。它只读 Newsletter。
2. **不做“稍后读”App：** 我们不开发阅读器 UI，Notion 就是唯一的 UI。
3. **不追求 100% 解析率：** 如果某封邮件排版太恶心，解析失败就失败了，不要为了 1% 的边缘情况浪费 50% 的开发时间。
4. **不急于 SaaS 化：** 在 MVP 跑通且自己爽用一个月之前，不考虑多租户、计费、用户管理。

---

## 3. 核心价值主张 (Value Proposition)

我们如何衡量这个项目的成功？

### Level 1: 个人效能 (The Efficiency Tool)

* **指标：**
* **Inbox Zero 时间：** 从每天 45 分钟降至 5 分钟。
* **信噪比：** 在 Notion 里看到的每一条，都是值得读的（Score > 60）。


* **价值：** 释放大脑带宽。把“筛选”交给 AI，把“思考”留给自己。

### Level 2: 知识复利 (The Knowledge Asset)

* **指标：**
* **知识库增长率：** 每周新增 20-50 条高质量技术情报。
* **搜索命中率：** 当我想找“React 新特性”时，能直接在 Notion 搜到两周前的 summary。


* **价值：** 构建个人知识库的“自动进货渠道”。

### Level 3: 潜在商业化 (The Curator Economy)

* **路径：**
* Tool (GistFlow) -> Asset (Notion Database) -> Product (Curated Newsletter/RSS).


* **价值：** 成为信息的“策展人”。如果你的 Prompt 调教得足够好，你筛选出的信息本身就是商品。

---

## 4. 风险预判与对策 (Pre-Mortem)

在开始写代码前，我们要直面可能导致项目失败的坑。

| 风险点 | 严重程度 | 对策方案 |
| --- | --- | --- |
| **Parsing Hell (解析地狱)** | 🔥🔥🔥 高 | 邮件 HTML 极度脏乱。**对策：** 使用 `trafilatura` 或 `markdownify` 等成熟库；容忍乱码；设置“原文链接”兜底。 |
| **Token Cost (API 成本)** | 🔥🔥 中 | 长邮件可能消耗大量 Token。**对策：** 截断过长文本；先用 Cheap Model (DeepSeek/GPT-3.5) 粗筛，再用 Expensive Model 精读。 |
| **Notion API Rate Limit** | 🔥 中 | 写入速度过快报错。**对策：** 严格的队列机制（Queue）和指数退避重试（Exponential Backoff）。 |
| **AI Hallucination (幻觉)** | 🔥 中 | AI 瞎编摘要。**对策：** 在 Prompt 中强制要求 "Output strictly based on provided text"；保留原文折叠块以便核对。 |

---

## 5. 执行路线图 (Execution Strategy)

我们采用 **“MVP + 迭代”** 模式，拒绝瀑布式开发。

1. **Phase 0: 验证期 (Current)**
* 目标：跑通 `Gmail -> Python -> LLM -> Notion` 的最小闭环。
* 标志：能把一封邮件变成 Notion 里的一行字。


2. **Phase 1: 可用期 (The "Dogfooding" Stage)**
* 目标：部署 Docker，7x24 小时运行。
* 标志：我自己每天早上只看 Notion，不再打开 Gmail 的 Newsletter 标签。


3. **Phase 2: 调优期 (The Prompt Engineering Stage)**
* 目标：让 AI 更懂我。
* 标志：调整 Prompt，使得打分机制（Score）真正反映我的喜好。


4. **Phase 3: 扩展期 (Optional)**
* 目标：RSS 输出、开源、分享给朋友。



---

## 6. 开发宪法 (Development Constitution)

* **Prompt is Logic:** 复杂的业务逻辑（如分类、提取重点）优先用 Prompt 解决，而不是写死板的 `if-else` 代码。
* **Fail Gracefully:** 一封邮件解析失败，绝对不能导致整个服务崩溃。Catch it, Log it, Skip it.
* **Keep Notion Clean:** Notion 是最终呈现端。如果 Notion 里的格式乱七八糟，后端写得再好也是零分。**排版优先级 = 代码优先级。**
