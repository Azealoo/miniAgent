# Mini-OpenClaw 开发需求⽂档 (PRD)

## Mini-OpenClaw 开发需求⽂档 (PRD)

## ⼀、项⽬介绍

## 1. 功能与⽬标定位

Mini-OpenClaw 是⼀个基于 Python 重构的、轻量级且⾼度透明的 AI Agent 系统,旨在复刻并优化 OpenClaw(原名 Moltbot/Clawdbot)的核⼼体验。

本项⽬不追求构建庞⼤的 SaaS 平台,⽽是致⼒于打造⼀个运⾏在本地的、拥有"真实记忆"的数字副 ⼿。其核⼼差异化定位在于:

- ⽂件即记忆 (File-first Memory):摒弃不透明的向量数据库,回归最原始、最通⽤的 Markdown/JSON ⽂件系统。⽤⼾的每⼀次对话、Agent 的每⼀次反思,都以⼈类可读的⽂件形式 存在。
- 技能即插件 (Skills as Plugins):遵循 Anthropic 的 Agent Skills 范式,通过⽂件夹结构管理能 ⼒,实现"拖⼊即⽤"的技能扩展。
- 透明可控:所有的 System Prompt 拼接逻辑、⼯具调⽤过程、记忆读写操作对开发者完全透明, 拒绝"⿊盒"Agent。

## 2. 项⽬核⼼技术架构

本项⽬要求完全采⽤ 前后端分离 架构,后端作为纯 API 服务运⾏。

- 后端语⾔:Python 3.10+ (强制使⽤ Type Hinting)。
- Web 框架:FastAPI (提供 RESTful 接⼝,⽀持异步处理)。
- Agent 编排引擎:LangChain 1.x (Stable Release)。
  - 核⼼ API:必须使⽤ create\_agent API ( from langchain.agents import create\_agent )。这是 LangChain 1.0 版本发布的最新标准 API,⽤于构建基于 Graph 运⾏ 时的 Agent。
  - 核⼼说明:严禁使⽤旧版的 AgentExecutor 或早期的 create\_react\_agent (旧链式 结构)。 create\_agent 底层虽然基于 LangGraph 运⾏时,但提供了更简洁的标准化接 ⼝,本项⽬应紧跟这⼀最新范式。
- RAG 检索引擎:LlamaIndex (LlamaIndex Core)。
  - ⽤于处理⾮结构化⽂档的混合检索(Hybrid Search),作为 Agent 的知识外挂。
- 模型接⼝:兼容 OpenAI API 格式(⽀持 OpenRouter, DeepSeek, Claude 等模型直连)。

• 模型接⼝:兼容 Ope 格式(⽀持 Ope oute , eepSee , Claude 等模型直连)。 • 数据存储:本地⽂件系统 (Local File System) 为主,不引⼊ MySQL/Redis 等重型依赖。

#### ⼆、内置⼯具

Mini-OpenClaw 在启动时,除了加载⽤⼾⾃定义的 Skills 外,必须内置以下 5 个核⼼基础⼯具(Core Tools)。根据"优先使⽤ LangChain 原⽣⼯具"的原则,技术选型更新如下:

## 1. 命令⾏操作⼯具 (Command Line Interface)

- 功能描述:允许 Agent 在受限的安全环境下执⾏ Shell 命令。
- 实现逻辑:
  - 直接使⽤ LangChain 内置⼯具: langchain\_community.tools.ShellTool 。
  - 配置要求:
    - 初始化时需配置 root\_dir 限制操作范围(沙箱化),防⽌ Agent 修改系统关键⽂件。
    - 需预置⿊名单拦截⾼危指令(如 rm -rf / )。
- ⼯具名称: terminal 。

#### 2. Python 代码解释器 (Python REPL)

- 功能描述:赋予 Agent 逻辑计算、数据处理和脚本执⾏的能⼒。
- 实现逻辑:
  - 直接使⽤ LangChain 内置⼯具:

langchain\_experimental.tools.PythonREPLTool 。

- 配置要求:
  - 该⼯具会⾃动创建⼀个临时的 Python 交互环境。
  - 注意:由于 PythonREPLTool 位于 experimental 包中,需确保依赖项安装正确。
- ⼯具名称: python\_repl 。

## 3. Fetch ⽹络信息获取

- 功能描述:⽤于获取指定 URL 的⽹⻚内容,Agent 联⽹的核⼼。
- 实现逻辑:
  - 直接使⽤ LangChain 内置⼯具:
  - langchain\_community.tools.RequestsGetTool 。 增强配置 (Wrapper):
    - 原⽣ RequestsGetTool 返回的是原始 HTML,Token 消耗巨⼤。
    - 必须封装:建议继承该类或创建⼀个 Wrapper,在获取内容后使⽤ BeautifulSoup 或 html2text 库清洗数据,仅返回 Markdown 或纯⽂本内容。

• ⼯具名称: fetch\_url 。

## 4. ⽂件读取⼯具 (File Reader)

- 功能描述:⽤于精准读取本地指定⽂件的内容。这是 Agent Skills 机制的核⼼依赖,⽤于读取 SKILL.md 的详细说明。
- 实现逻辑:
  - 直接使⽤ LangChain 内置⼯具:

langchain\_community.tools.file\_management.ReadFileTool 。

- 配置要求:
  - 必须设置 root\_dir 为项⽬根⽬录,严禁 Agent 读取项⽬以外的系统⽂件。
- ⼯具名称: read\_file 。

## 5. RAG 检索⼯具 (Hybrid Retrieval)

- 功能描述:当⽤⼾询问具体的知识库内容(⾮对话历史)时,Agent 可调⽤此⼯具进⾏深度检索。
- 技术选型:LlamaIndex。
- 实现逻辑:
  - 索引构建:⽀持扫描指定⽬录(如 knowledge/ )下的 PDF/MD/TXT ⽂件,构建本地索引。
  - 混合检索:必须实现 Hybrid Search(关键词检索 BM25 + 向量检索 Vector Search)。
  - 持久化:索引⽂件需持久化存储在本地( storage/ )。
- ⼯具名称: search\_knowledge\_base 。

## 三、mini OpenClaw 的 Agent Skills 系统

#### 1. Agent Skills 基础功能介绍

mini OpenClaw 的 Agent Skills 遵循 "Instruction-following" (指令遵循) 范式,⽽⾮传统的 "Function-calling" (函数调⽤) 范式。这意味着 Skills 本质上是教会 Agent 如何使⽤基础⼯具(如 Python/Terminal)去完成任务的说明书,⽽不是预先写好的 Python 函数。

Agent Skills 以⽂件夹形式存在于 backend/skills/ ⽬录下。

## 2. Agent Skills 载⼊与执⾏流程

#### 2.1 Agent Skills 读取流程 (Bootstrap)

在 Agent 启动或会话开始时,系统扫描 skills ⽂件夹,读取每个 SKILL.md 的元数据 (Frontmatter),并将其汇总⽣成 SKILLS\_SNAPSHOT.md 。

#### SKILLS\_SNAPSHOT.md ⽰例:

```
Code<balvoaciklable_skills>
     <skill>
       <name>get_weather</name>
       <description>获取指定城市的实时天⽓信息</description>
       <location>./backend/skills/get_weather/SKILL.md</location>
     </skill>
   </available_skills>
1
2
3
4
5
6
7
```

注意: location 使⽤相对路径。

#### 2.2 Agent Skills 调⽤流程 (Execution)

这是本系统最独特的地⽅:

1. 感知:Agent 在 System Prompt 中看到 available\_skills 列表。

2. 决策:当⽤⼾请求"查询北京天⽓"时,Agent 发现 get\_weather 技能匹配。

- 3. ⾏动 (Tool Call):Agent 不调⽤ get\_weather() 函数(因为它不存在),⽽是调⽤ read\_file(path="./backend/skills/get\_weather/SKILL.md") 。
- 4. 学习与执⾏:Agent 读取 Markdown 内容,理解操作步骤(例如:"使⽤ fetch\_url 访问某天⽓ API" 或 "使⽤ python\_repl 运⾏以下代码"),然后动态调⽤ Core Tools (Terminal/Python) 来完成任务。

## 四、mini OpenClaw 对话记忆管理系统设计

## 1. 本地优先原则

所有记忆⽂件(Markdown/JSON)均存储在本地⽂件系统,确保完全的数据主权和可解释性。

## 2. 系统提⽰词 (System Prompt) 构成

System Prompt 由以下 6 部分动态拼接⽽成(按顺序):

- 1. SKILLS\_SNAPSHOT.md (能⼒列表)
- 2. SOUL.md (核⼼设定)
- 3. IDENTITY.md (⾃我认知)
- 4. USER.md (⽤⼾画像)
- 5. AGENTS.md (⾏为准则 & 记忆操作指南)
- 6. MEMORY.md (⻓期记忆)

截断策略:如果拼接后 Token 超出模型限制(或单⽂件超 20k 字符),需对超⻓部分进⾏截断并在末 尾添加 ...[truncated] 标识。

## 3. AGENTS.md 的默认配置 (核⼼修正)

由于 Agent 默认并不知道它是通过"阅读⽂件"来学习技能的,因此必须在初始化时⽣成⼀个包含明 确指令的 AGENTS.md 。

• 必须包含的元指令 (Meta-Instructions):

```
Code block
   # 操作指南
   ## 技能调⽤协议 (SKILL PROTOCOL)
   你拥有⼀个技能列表 (SKILLS_SNAPSHOT),其中列出了你可以使⽤的能⼒及其定义⽂件的位置。
   **当你要使⽤某个技能时,必须严格遵守以下步骤:**
   1. 你的第⼀步⾏动永远是使⽤ `read_file` ⼯具读取该技能对应的 `location` 路径下的
   Markdown ⽂件。
   2. 仔细阅读⽂件中的内容、步骤和⽰例。
   3. 根据⽂件中的指⽰,结合你内置的 Core Tools (terminal, python_repl, fetch_url) 来
   执⾏具体任务。
   **禁⽌**直接猜测技能的参数或⽤法,必须先读取⽂件!
   ## 记忆协议
   ...
1
2
3
4
5
6
7
8
9
10
11
12
```

## 4. 会话存储 (Sessions)

- 路径: backend/sessions/{session\_name}.json
- 格式:标准 JSON 数组,包含 user , assistant , tool (function calls) 类型的完整消息记 录。

## 五、后端 API 接⼝规范 (FastAPI)

后端服务作为独⽴进程运⾏,负责 Agent 逻辑、⽂件读写和状态管理。

• 服务端⼝: 8002

• 基础 URL: [http://localhost:8002](http://localhost:8002/)

## 1. 核⼼对话接⼝

- Endpoint: POST /api/chat
- 功能: 发送⽤⼾消息,获取 Agent 回复。
- Request:

```
Code block
   {
     "message": "查询⼀下北京的天⽓",
1
2
```

```
"session_id": "main_session",
      "stream": true
    }
3
4
5
```

• Response: ⽀持 SSE (Server-Sent Events) 流式输出,实时推送 Agent 的思考过程 (Thought/Tool Calls) 和最终回复。

#### 2. ⽂件管理接⼝ (⽤于前端编辑器)

• Endpoint: GET /api/files

◦ Query: path=memory/MEMORY.md

◦ 功能: 读取指定⽂件的内容。

• Endpoint: POST /api/files

◦ Body: { "path": "...", "content": "..." }

◦ 功能: 保存对 Memory 或 Skill ⽂件的修改。

#### 3. 会话管理接⼝

• Endpoint: GET /api/sessions

◦ 功能: 获取所有历史会话列表。

## 六、前端开发要求

## 1. 设计理念与布局架构

前端采⽤ IDE(集成开发环境)⻛格,三栏式布局。

- 左侧 (Sidebar):导航 (Chat/Memory/Skills) + 会话列表。
- 中间 (Stage):对话流 + 思考链可视化 (Collapsible Thoughts)。
- 右侧 (Inspector):Monaco Editor,⽤于实时查看/编辑正在使⽤的 SKILL.md 或 MEMORY.md 。

## 2. 技术栈

- 框架: Next.js 14+ (App Router), TypeScript
- UI: Shadcn/UI, Tailwind CSS, Lucide Icons
- Editor: Monaco Editor (配置为 Light Theme)

#### 3. UI/UX ⻛格规范

• ⾊调: 浅⾊ Apple ⻛格 (Frosty Glass)。

- 背景:纯⽩/极浅灰 ( #fafafa ),⾼透⽑玻璃效果。
- 强调⾊:克莱因蓝 (Klein Blue) 或 活⼒橙。
- 导航栏: 顶部固定,半透明。
  - 左中:"mini OpenClaw"
  - 右侧:"赋范空间" (链接⾄ [https://fufan.ai](https://fufan.ai/) )。

## 七、项⽬⽬录结构参考

建议 Claude Code 按照以下结构进⾏初始化:

```
Code block
   mini-openclaw/
   ├── backend/ # FastAPI + LangChain/LangGraph
   │ ├── app.py # ⼊⼝⽂件 (Port 8002)
   │ ├── memory/ # 记忆存储
   │ │ ├── logs/ # Daily logs
   │ │ └── MEMORY.md # Core memory
   │ ├── sessions/ # JSON 会话记录
   │ ├── skills/ # Agent Skills ⽂件夹
   │ │ └── get_weather/
   │ │ └── SKILL.md
   │ ├── workspace/ # System Prompts (SOUL.md, etc.)
   │ ├── tools/ # Core Tools 实现
   │ ├── graph/ # LangGraph 状态机定义
   │ └── requirements.txt
   │
   ├── frontend/ # Next.js 14+
   │ ├── src/
   │ │ ├── app/
   │ │ ├── components/
   │ │ │ ├── chat/ # 聊天组件
   │ │ │ └── editor/ # Monaco Wrapper
   │ │ └── lib/
   │ │ └── api.ts # Fetch wrapper for port 8002
   │ └── package.json
   │
   └── README.md
1
2
3
4
5
6
7
8
9
10
11
12
13
14
15
16
17
18
19
20
21
22
23
24
25
26
```