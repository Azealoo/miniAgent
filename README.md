# Mini-OpenClaw README

## Mini-OpenClaw

⼀个轻量级、全透明的 AI Agent 系统。强调⽂件驱动(Markdown/JSON 取代向量数据库)、指令式 技能(⽽⾮ function-calling)、以及 Agent 全部操作过程的可视化。

### ⽬录

- 技术选型
- 项⽬结构
- 环境配置
- 启动⽅式
- 后端架构详解
  - 应⽤⼊⼝ app.py
  - Agent 引擎 graph/
  - 五⼤核⼼⼯具 tools/
  - API 层 api/
  - System Prompt 组装
  - 会话存储格式
  - Skills 技能系统
- 前端架构概览
- 核⼼数据流
  - ⽤⼾发送消息
  - RAG 检索模式
  - 对话压缩
- 关键设计决策
- API 接⼝速查

## 技术选型

| 层级        | 技术                                | 说明                                              |
|-----------|-----------------------------------|-------------------------------------------------|
| 后端框架      | FastAPI + Uvicorn                 | 异步<br>HTTP + SSE 流式推送                           |
| Agent 引擎  | LangChain 1.x create_agent        | ⾮<br>AgentExecutor ,⾮遗留<br>create_react_agent   |
| LLM       | DeepSeek(langchain<br>deepseek)   | 通过<br>ChatDeepSeek 原⽣接⼊,<br>兼容<br>OpenAI API 格式 |
| RAG       | LlamaIndex Core                   | 向量检索<br>+ BM25 混合搜索                             |
| Embedding | OpenAI text-embedding-3-<br>small | 通过<br>OPENAI_BASE_URL 可切换<br>代理                 |
| Token 计数  | tiktoken cl100k_base              | 精确<br>token 统计                                  |
| 前端框架      | Next.js 14 App Router             | TypeScript + React 18                           |
| UI        | Tailwind CSS + Shadcn/UI ⻛格       | ⽑玻璃效果<br>Apple ⻛                                |
| 代码编辑器     | Monaco Editor                     | 在线编辑<br>Memory/Skill ⽂件                         |
| 状态管理      | React Context                     | ⽆<br>Redux,单⼀<br>AppProvider                    |
| 存储        | 本地⽂件系统                            | ⽆<br>MySQL/Redis,JSON<br>+<br>Markdown ⽂件       |

## 项⽬结构

```
Code block
   mini-OpenClaw/
   ├── backend/
   │ ├── app.py # FastAPI ⼊⼝,路由注册,启动初始化
   │ ├── config.py # 全局配置管理(config.json 持久化)
   │ ├── requirements.txt # Python 依赖
   │ ├── .env.example # 环境变量模板
   │ │
   │ ├── api/ # API 路由层
   │ │ ├── chat.py # POST /api/chat — SSE 流式对话
   │ │ ├── sessions.py # 会话 CRUD + 标题⽣成
   │ │ ├── files.py # ⽂件读写 + 技能列表
   │ │ ├── tokens.py # Token 统计
   │ │ ├── compress.py # 对话压缩
   │ │ └── config_api.py # RAG 模式开关
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
```

```
│ │
   │ ├── graph/ # Agent 核⼼逻辑
   │ │ ├── agent.py # AgentManager — 构建 & 流式调⽤
   │ │ ├── session_manager.py # 会话持久化(JSON ⽂件)
   │ │ ├── prompt_builder.py # System Prompt 组装器
   │ │ └── memory_indexer.py # MEMORY.md 向量索引(RAG)
   │ │
   │ ├── tools/ # 5 个核⼼⼯具
   │ │ ├── __init__.py # ⼯具注册⼯⼚
   │ │ ├── terminal_tool.py # 沙箱终端
   │ │ ├── python_repl_tool.py # Python 解释器
   │ │ ├── fetch_url_tool.py # ⽹⻚抓取(HTML→Markdown)
   │ │ ├── read_file_tool.py # 沙箱⽂件读取
   │ │ ├── search_knowledge_tool.py # 知识库搜索
   │ │ └── skills_scanner.py # 技能⽬录扫描器
   │ │
   │ ├── workspace/ # System Prompt 组件
   │ │ ├── SOUL.md # ⼈格、语⽓、边界
   │ │ ├── IDENTITY.md # 名称、⻛格、Emoji
   │ │ ├── USER.md # ⽤⼾画像
   │ │ └── AGENTS.md # 操作指南 & 记忆/技能协议
   │ │
   │ ├── skills/ # 技能⽬录(每个技能⼀个⼦⽬录)
   │ │ └── get_weather/SKILL.md # ⽰例:天⽓查询技能
   │ ├── memory/MEMORY.md # 跨会话⻓期记忆
   │ ├── knowledge/ # 知识库⽂档(供 RAG 检索)
   │ ├── sessions/ # 会话 JSON ⽂件
   │ │ └── archive/ # 压缩归档
   │ ├── storage/ # LlamaIndex 持久化索引
   │ │ └── memory_index/ # MEMORY.md 专⽤索引
   │ └── SKILLS_SNAPSHOT.md # 技能快照(启动时⾃动⽣成)
   │
   └── frontend/
     └── src/
        ├── app/
        │ ├── layout.tsx # Next.js 根布局
        │ ├── page.tsx # 主⻚⾯(三栏布局)
        │ └── globals.css # 全局样式
        ├── lib/
        │ ├── store.tsx # React Context 状态管理
        │ └── api.ts # 后端 API 客⼾端
        └── components/
           ├── chat/
           │ ├── ChatPanel.tsx # 聊天⾯板(消息列表 + 输⼊框)
           │ ├── ChatMessage.tsx # 消息⽓泡(Markdown 渲染)
           │ ├── ChatInput.tsx # 输⼊框
           │ ├── ThoughtChain.tsx # ⼯具调⽤思维链(可折叠)
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
27
28
29
30
31
32
33
34
35
36
37
38
39
40
41
42
43
44
45
46
47
48
49
50
51
52
53
54
55
56
57
58
59
60
61
```

```
│ └── RetrievalCard.tsx # RAG 检索结果卡⽚
             ├── layout/
             │ ├── Navbar.tsx # 顶部导航栏
             │ ├── Sidebar.tsx # 左侧边栏(会话列表 + Raw Messages)
             │ └── ResizeHandle.tsx # ⾯板拖拽分隔条
             └── editor/
                └── InspectorPanel.tsx # 右侧检查器(Monaco 编辑器)
62
63
64
65
66
67
68
```

### 环境配置

复制 .env.example 为 .env 并填⼊ API Key:

```
Code block
   cd backend
   cp .env.example .env
Code block
   # DeepSeek(Agent 主模型)
   DEEPSEEK_API_KEY=sk-xxx
   DEEPSEEK_BASE_URL=https://api.deepseek.com
   DEEPSEEK_MODEL=deepseek-chat
   # OpenAI(Embedding 模型,⽤于知识库 & RAG 检索)
   OPENAI_API_KEY=sk-xxx
   OPENAI_BASE_URL=https://api.openai.com/v1
   EMBEDDING_MODEL=text-embedding-3-small
1
2
1
2
3
4
5
6
7
8
9
```

OPENAI\_BASE\_URL ⽀持换成任意兼容 OpenAI Embedding 接⼝的代理地址。

### 启动⽅式

```
Code block
   # 后端(端⼝ 8002)
   cd backend
   pip install -r requirements.txt
   uvicorn app:app --port 8002 --host 0.0.0.0 --reload
   # 前端(端⼝ 3000)
1
2
3
4
5
6
```

- cd frontend 7
- npm install 8
- npm run dev 9

本机访问 [http://localhost:3000](http://localhost:3000/) ,局域⽹内其他设备访问 http://<本机IP>:3000 。

## 后端架构详解

### 应⽤⼊⼝ app.py

启动时通过 lifespan 执⾏三步初始化:

#### Code block

- 1. scan\_skills() → 扫描 skills/\*\*/SKILL.md,⽣成 SKILLS\_SNAPSHOT.md 1
- 2. agent\_manager.initialize() → 创建 ChatDeepSeek LLM 实例,注册 5 个⼯具 2
- 3. memory\_indexer.rebuild\_index() → 构建 MEMORY.md 向量索引(供 RAG 使⽤) 3

随后注册 6 个 API 路由模块,所有路由统⼀挂载在 /api 前缀下。

## Agent 引擎 graph/

### agent.py — AgentManager

核⼼单例类,管理 Agent 的⽣命周期。

| ⽅法                        | 职责                                                              |
|---------------------------|-----------------------------------------------------------------|
| initialize(base_dir)      | 创建<br>ChatDeepSeek LLM、加载⼯具列表、初始化<br>SessionManager             |
| _build_agent()            | 每次调⽤都重建,确保读取最新的<br>System Prompt 和<br>RAG 配置                    |
| _build_messages()         | 将会话历史(dict<br>列表)转换为<br>LangChain 的<br>HumanMessage / AIMessage |
| astream(message, history) | 核⼼流式⽅法,依次<br>yield 6 种事件                                        |

### astream() 的流式事件序列:

```
[RAG模式] retrieval → token... → tool_start → tool_end → new_response →
   token... → done
   [普通模式] token... → tool_start → tool_end → new_response →
   token... → done
1
2
```

#### 关键机制:

- 多段响应:Agent 每次执⾏完⼯具后再次⽣成⽂本时,会 yield ⼀个 new\_response 事件,前端 据此创建新的助⼿消息⽓泡
- RAG 注⼊:如果开启 RAG 模式,在调⽤ Agent 之前先检索 MEMORY.md,将结果作为临时上下⽂ 追加到 history 尾部(不持久化到会话⽂件)

### session\_manager.py — 会话持久化

以 JSON ⽂件管理每个会话的完整历史。

### 核⼼⽅法:

| ⽅法                                             | 说明                                                                 |
|------------------------------------------------|--------------------------------------------------------------------|
| load_session(id)                               | 返回原始消息数组                                                           |
| load_session_for_agent(id)                     | 为<br>LLM 优化:合并连续的<br>assistant 消息、注⼊<br>compressed_context         |
| save_message(id, role, content,<br>tool_calls) | 追加消息到<br>JSON ⽂件                                                   |
| compress_history(id, summary, n)               | N 条消息到<br>归档前<br>sessions/archive/ ,摘要写<br>⼊<br>compressed_context |
| get_compressed_context(id)                     | 获取压缩摘要(多次压缩⽤<br>分隔)                                                |

load\_session\_for\_agent() 与 load\_session() 的区别:LLM 要求严格的 user/assistant 交替,⽽实际存储中可能有连续多条 assistant 消息(⼯具调⽤产⽣的多段响应),此 ⽅法将它们合并为单条。如果存在 compressed\_context ,还会在消息列表头部插⼊⼀条虚拟的 assistant 消息承载历史摘要。

## prompt\_builder.py — System Prompt 组装

按固定顺序拼接 6 个 Markdown ⽂件为完整的 System Prompt:

#### Code block

- ① SKILLS\_SNAPSHOT.md 可⽤技能清单 1
- ② workspace/SOUL.md ⼈格、语⽓、边界 2

- ③ workspace/IDENTITY.md 名称、⻛格 3
- ④ workspace/USER.md ⽤⼾画像 4
- ⑤ workspace/AGENTS.md 操作指南 & 协议 5
- 6
- ⑥ memory/MEMORY.md 跨会话⻓期记忆(RAG 模式下跳过)

每个⽂件内容上限 20,000 字符,超出则截断并标记 ...[truncated] 。

RAG 模式下的变化:跳过 MEMORY.md,改为追加⼀段 RAG 引导语,告知 Agent 记忆将通过检索动态 注⼊。

### memory\_indexer.py — MEMORY.md 向量索引

专⻔为 memory/MEMORY.md 构建的 LlamaIndex 向量索引,独⽴于知识库索引(存储路径 storage/memory\_index/ )。

| ⽅法                       | 说明                                                                                                                  |
|--------------------------|---------------------------------------------------------------------------------------------------------------------|
| rebuild_index()          | 读取<br>MEMORY.md →<br>SentenceSplitter(chunk_size=256,<br>构建<br>overlap=32) 切⽚<br>→<br>VectorStoreIndex →<br>持<br>久化 |
| retrieve(query, top_k=3) | 语义检索,返回<br>[{text, score, source}]                                                                                  |
| _maybe_rebuild()         | MD5 检查⽂件是否变更,变更则⾃动<br>每次检索前通过<br>重建                                                                                 |

另外,当⽤⼾通过 Monaco 编辑器保存 MEMORY.md 时, files.py 的 save\_file 端点也会主 动触发 rebuild\_index() 。

## 五⼤核⼼⼯具 tools/

所有⼯具均继承 LangChain 的 BaseTool ,通过 tools/\_\_init\_\_.py 的 get\_all\_tools(base\_dir) 统⼀注册。

| ⼯具       | ⽂件               | 功能             | 安全措施                                                                                             |
|----------|------------------|----------------|--------------------------------------------------------------------------------------------------|
| terminal | terminal_tool.py | 执⾏<br>Shell 命令 | ⿊名单(<br>rm -rf / 、<br>mkfs 、<br>shutdown<br>等);CWD<br>限制在项⽬<br>根⽬录;30s<br>超时;输出<br>截断<br>5000 字符 |
|          |                  |                |                                                                                                  |

| python_repl               | python_repl_tool.p<br>y      | 执⾏<br>Python 代码 | 封装<br>LangChain 原⽣<br>PythonREPLTool                                                   |
|---------------------------|------------------------------|-----------------|----------------------------------------------------------------------------------------|
| fetch_url                 | fetch_url_tool.py            | 抓取⽹⻚内容          | ⾃动识别<br>JSON/HTML;<br>HTML 通过<br>html2text 转<br>超时;<br>Markdown;15s<br>输出截断<br>5000 字符 |
| read_file                 | read_file_tool.py            | 读取项⽬内⽂件         | 路径遍历检查(不可逃逸<br>出<br>root_dir );输出<br>截断<br>10,000 字符                                   |
| search_knowledge_b<br>ase | search_knowledge_to<br>ol.py | 搜索知识库           | 惰性加载索引;从<br>knowledge/ ⽬录构<br>建;top-3<br>语义检索;索<br>引持久化到<br>storage/                   |

### skills\_scanner.py

⾮⼯具,⽽是启动时执⾏的扫描器:遍历 skills/\*/SKILL.md ,解析 YAML frontmatter ( name 、 description ),⽣成 XML 格式的 SKILLS\_SNAPSHOT.md 。该快照被纳⼊ System Prompt,让 Agent 知道有哪些可⽤技能。

### API 层 api/

## chat.py — 流式对话

POST /api/chat 是系统的核⼼端点。

### 请求体:

```
Code block
```

{"message": "你好", "session\_id": "abc123", "stream": true} 1

#### 内部流程:

- 1. 调⽤ session\_manager.load\_session\_for\_agent() 获取经过合并优化的历史
- 2. 判断是否为会话的第⼀条消息(⽤于后续⾃动⽣成标题)
- 3. 创建 event\_generator() ,内部调⽤ agent\_manager.astream()
- 4. 按段(segment)追踪响应⸺每次⼯具执⾏后 Agent 重新⽣成⽂本时开启新段
- 5. done 事件到达后:保存⽤⼾消息 + 每段助⼿消息到会话⽂件

## 6. 如果是⾸条消息,额外调⽤ DeepSeek ⽣成 ≤10 字的中⽂标题 SSE 事件类型:

| 事件           | 数据                    | 触发时机                          |
|--------------|-----------------------|-------------------------------|
| retrieval    | {query, results}      | RAG 模式检索完成后                   |
| token        | {content}             | LLM 输出每个<br>token             |
| tool_start   | {tool, input}         | Agent 调⽤⼯具前                   |
| tool_end     | {tool, output}        | ⼯具返回结果后                       |
| new_response | {}                    | ⼯具执⾏完毕、Agent<br>开始新⼀轮<br>⽂本⽣成 |
| done         | {content, session_id} | 整轮响应结束                        |
| title        | {session_id, title}   | ⾸次对话后⾃动⽣成标题                   |
| error        | {error}               | 发⽣异常                          |

### sessions.py — 会话管理

| 端点                                    | ⽅法     | 说明                                             |
|---------------------------------------|--------|------------------------------------------------|
| /api/sessions                         | GET    | 列出所有会话(按更新时间倒序)                                |
| /api/sessions                         | POST   | 创建新会话(UUID<br>命名)                              |
| /api/sessions/{id}                    | PUT    | 重命名会话                                          |
| /api/sessions/{id}                    | DELETE | 删除会话                                           |
| /api/sessions/{id}/messag<br>es       | GET    | 获取完整消息(含<br>System<br>Prompt)                  |
| /api/sessions/{id}/histor<br>y        | GET    | 获取对话历史(不含<br>System<br>Prompt,含<br>tool_calls) |
| /api/sessions/{id}/generat<br>e-title | POST   | AI ⽣成标题                                        |

### files.py — ⽂件操作

| 端点               | ⽅法   | 说明         |
|------------------|------|------------|
| /api/files?path= | GET  | 读取⽂件内容     |
| /api/files       | POST | 保存⽂件(编辑器⽤) |
| /api/skills      | GET  | 列出可⽤技能     |

### 路径⽩名单机制:

- 允许的⽬录前缀: workspace/ 、 memory/ 、 skills/ 、 knowledge/
- 允许的根⽬录⽂件: SKILLS\_SNAPSHOT.md
- 包含路径遍历检测( .. 攻击防护)

保存 memory/MEMORY.md 时会⾃动触发 memory\_indexer.rebuild\_index() 。

### tokens.py — Token 统计

| 端点                       | ⽅法   | 说明                                                        |
|--------------------------|------|-----------------------------------------------------------|
| /api/tokens/session/{id} | GET  | 返回<br>{system_tokens,<br>message_tokens,<br>total_tokens} |
| /api/tokens/files        | POST | 批量统计⽂件<br>token 数,body:<br>{paths: []}                    |

使⽤ tiktoken 的 cl100k\_base 编码器,与 GPT-4 系列⼀致。

### compress.py — 对话压缩

| 端点                              | ⽅法   | 说明              |
|---------------------------------|------|-----------------|
| /api/sessions/{id}/compre<br>ss | POST | 压缩前<br>50% 历史消息 |

#### 流程:

- 1. 检查消息数量 ≥ 4
- 2. 取前 50% 消息(最少 4 条)
- 3. 调⽤ DeepSeek(temperature=0.3)⽣成中⽂摘要(≤500 字)
- 4. 调⽤ session\_manager.compress\_history() 归档 + 写⼊摘要

```
5. 返回 {archived_count, remaining_count}
```

归档⽂件存储在 sessions/archive/{session\_id}\_{timestamp}.json 。

### config\_api.py — 配置管理

| 端点                   | ⽅法  | 说明                                    |
|----------------------|-----|---------------------------------------|
| /api/config/rag-mode | GET | 获取<br>RAG 模式状态                        |
| /api/config/rag-mode | PUT | 切换<br>RAG 模式,body:<br>{enabled: bool} |

配置持久化到 backend/config.json 。

### System Prompt 组装

Agent 每次被调⽤时都会重新读取所有 Markdown ⽂件并组装 System Prompt,确保 workspace ⽂ 件的实时编辑能⽴即⽣效:

```
Code block
   ┌───────────────────────────────────┐
   │ <!-- Skills Snapshot --> │ ← SKILLS_SNAPSHOT.md
   │ <!-- Soul --> │ ← workspace/SOUL.md
   │ <!-- Identity --> │ ← workspace/IDENTITY.md
   │ <!-- User Profile --> │ ← workspace/USER.md
   │ <!-- Agents Guide --> │ ← workspace/AGENTS.md
   │ <!-- Long-term Memory --> │ ← memory/MEMORY.md(RAG 模式下替换为引导
   语)
   └───────────────────────────────────┘
1
2
3
4
5
6
7
8
```

每个组件间以 \n\n 分隔,每个组件带 HTML 注释标签便于调试定位。

### 会话存储格式

⽂件路径: sessions/{session\_id}.json

```
Code block
   {
     "title": "讨论天⽓查询",
     "created_at": 1706000000.0,
1
2
3
```

```
"updated_at": 1706000100.0,
      "compressed_context": "⽤⼾之前询问了北京天⽓...",
      "messages": [
        { "role": "user", "content": "北京天⽓怎么样?" },
        {
          "role": "assistant",
          "content": "让我查⼀下...",
          "tool_calls": [
            { "tool": "terminal", "input": "curl wttr.in/Beijing", "output": "..."
    }
          ]
        },
        { "role": "assistant", "content": "北京今天晴,⽓温 25°C。" }
      ]
    }
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
```

### 说明:

- v1 兼容:如果⽂件内容是纯数组 [...] , \_read\_file() 会⾃动迁移为 v2 格式
- 多段 assistant:⼀次⼯具调⽤后会产⽣多条连续的 assistant 消息
- compressed\_context:可选字段,多次压缩⽤ --- 分隔

## Skills 技能系统

技能不是 Python 函数,⽽是纯 Markdown 指令⽂件。Agent 通过 read\_file ⼯具读取 SKILL.md,理解步骤后⽤核⼼⼯具执⾏。

### ⽬录结构:

```
Code block
    skills/
    └── get_weather/
        └── SKILL.md
1
2
3
```

### SKILL.md 格式:

```
Code block
   ---
   name: 天⽓查询
   description: 查询指定城市的天⽓信息
   ---
1
2
3
4
5
```

```
## 步骤
    1. 使⽤ `fetch_url` ⼯具访问 wttr.in/{城市名}
    2. 解析返回的天⽓数据
    3. 以友好的格式回复⽤⼾
6
7
8
9
10
```

启动时 skills\_scanner.py 扫描所有技能,⽣成 SKILLS\_SNAPSHOT.md 供 Agent 参考。

### 前端架构概览

三栏 IDE ⻛格布局,基于 Flexbox + 可拖拽分隔条:

```
Code block
  ┌──────────────────────────────────────────────────────────┐
  │ Navbar(mini OpenClaw / 赋范空间) │
  ├──────────┬──────────────────────────┬────────────────────┤
  │ Sidebar │ ChatPanel │ InspectorPanel │
  │ │ │ │
  │ 会话列表 │ 消息⽓泡 │ Memory / Skills │
  │ │ ├─ ThoughtChain │ ⽂件列表 │
  │ Raw Msgs │ ├─ RetrievalCard │ Monaco 编辑器 │
  │ 扳⼿/RAG │ └─ Markdown 内容 │ Token 统计 │
  │ Token 统计│ │ │
  │ │ ChatInput │ │
  ├──────────┴──────────────────────────┴────────────────────┤
  │ ResizeHandle (可拖拽) │
  └──────────────────────────────────────────────────────────┘
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
```

状态管理:全部通过 store.tsx 的 React Context 管理,包括消息列表、会话切换、⾯板宽度、流 式状态、压缩状态、RAG 模式等。

### API 客⼾端( api.ts ):

- streamChat() 实现了⾃定义的 SSE 解析器(因为浏览器原⽣ EventSource 只⽀持 GET, ⽽聊天接⼝是 POST)
- API\_BASE 动态取 window.location.hostname ,⾃动适配本机 / 局域⽹访问

## 核⼼数据流

### ⽤⼾发送消息

```
Code前b端lock 后端
   │
   ├─ store.sendMessage(text)
   │ ├─ 创建 user + assistant 占位消息
   │ └─ streamChat(text, sessionId) ──────→ POST /api/chat
   │ │
   │ ├─ load_session_for_agent()
   │ │ ├─ 合并连续 assistant 消息
   │ │ └─ 注⼊ compressed_context
   │ │
   │ ├─ [RAG]
  memory_indexer.retrieve()
   │ │ └─ yield retrieval 事件
   │ │
   │ ├─ _build_agent()
   │ │ ├─ build_system_prompt()
   │ │ └─ create_agent(llm, tools,
  prompt)
   │ │
   │ ← SSE: token ──────────────────────────├─ agent.astream()
   │ ← SSE: tool_start ────────────────────│ ├─ yield
  token/tool_start/tool_end
   │ ← SSE: tool_end ──────────────────────│ └─ yield done
   │ ← SSE: new_response ──────────────────│
   │ ← SSE: token ──────────────────────────│
   │ ← SSE: done ───────────────────────────├─ save_message(user +
  assistant segments)
   │ │
   │ ← SSE: title ──────────────────────────└─ [⾸次] _generate_title()
   │
   ├─ 实时更新 messages state
   └─ 刷新 sessions 列表
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
27
28
```

## RAG 检索模式

```
Code block
   ⽤⼾开启 RAG ──→ PUT /api/config/rag-mode {enabled: true}
                    └─ config.json 写⼊ {"rag_mode": true}
   ⽤⼾发送消息 ──→ agent.astream()
                    │
                    ├─ get_rag_mode() → true
                    ├─ memory_indexer.retrieve(query)
                    │ ├─ _maybe_rebuild() // MD5 检测变更
                    │ └─ index.as_retriever(top_k=3)
1
2
3
4
5
6
7
8
9
```

```
│
                   ├─ yield {"type": "retrieval", results: [...]}
                   ├─ 将检索结果拼接为 "[记忆检索结果]" 上下⽂
                   └─ 追加到 history 末尾(仅当次请求,不持久化)
    前端收到 retrieval 事件 ──→ 存⼊ message.retrievals
                            └─ RetrievalCard 渲染紫⾊折叠卡⽚
10
11
12
13
14
15
16
```

### 对话压缩

```
Code block
    ⽤⼾点击扳⼿ ──→ 确认弹窗 ──→ POST /api/sessions/{id}/compress
                                │
                                ├─ 取前 50% 消息(≥4 条)
                                ├─ DeepSeek ⽣成中⽂摘要(≤500字)
                                ├─ 归档到 sessions/archive/
                                ├─ 从 session 中删除这些消息
                                └─ 摘要写⼊ compressed_context
    下次调⽤ Agent ──→ load_session_for_agent()
                     └─ 在消息列表头部插⼊:
                        {"role": "assistant", "content": "[以下是之前对话的摘
    要]\n{摘要}"}
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
```

### 关键设计决策

| 决策                                       | 理由                                              |
|------------------------------------------|-------------------------------------------------|
| 使⽤<br>create_agent() ⽽⾮<br>AgentExecutor | LangChain 1.x 推荐的现代<br>API,⽀持原⽣流式               |
| 每次请求重建<br>Agent                          | 确保<br>System Prompt 反映<br>workspace ⽂件的实时编<br>辑 |
| ⽂件驱动⽽⾮数据库                                | 降低部署⻔槛,所有状态对开发者透明可查                             |
| 技能<br>= Markdown 指令                      | Agent ⾃主阅读并执⾏,不需要注册新的<br>Python 函数              |
| 多段响应分别存储                                 | 忠实保留⼯具调⽤前后的⽂本段,Raw<br>Messages 可<br>完整审查        |
| System Prompt 组件截断<br>20K                | 防⽌<br>MEMORY.md 膨胀导致上下⽂溢出                       |
|                                          |                                                 |

| RAG 检索结果不持久化                          | 避免会话⽂件膨胀,检索上下⽂仅⽤于当次请求 |
|---------------------------------------|-----------------------|
| 路径⽩名单<br>+ 遍历检测                       | 双重防护,终端和⽂件读取⼯具均受沙箱约束  |
| window.location.hostname 动态<br>API 地址 | ⼀份代码同时⽀持本机和局域⽹访问      |

## API 接⼝速查

| 路径                                    | ⽅法     | 说明                            |
|---------------------------------------|--------|-------------------------------|
| /api/chat                             | POST   | SSE 流式对话                      |
| /api/sessions                         | GET    | 列出所有会话                        |
| /api/sessions                         | POST   | 创建新会话                         |
| /api/sessions/{id}                    | PUT    | 重命名会话                         |
| /api/sessions/{id}                    | DELETE | 删除会话                          |
| /api/sessions/{id}/messag<br>es       | GET    | 获取完整消息(含<br>System<br>Prompt) |
| /api/sessions/{id}/histor<br>y        | GET    | 获取对话历史                        |
| /api/sessions/{id}/generat<br>e-title | POST   | AI ⽣成标题                       |
| /api/sessions/{id}/compre<br>ss       | POST   | 压缩对话历史                        |
| /api/files?path=                      | GET    | 读取⽂件                          |
| /api/files                            | POST   | 保存⽂件                          |
| /api/skills                           | GET    | 列出技能                          |
| /api/tokens/session/{id}              | GET    | 会话<br>Token 统计                |
| /api/tokens/files                     | POST   | ⽂件<br>Token 统计                |
| /api/config/rag-mode                  | GET    | 获取<br>RAG 模式状态                |
| /api/config/rag-mode                  | PUT    | 切换<br>RAG 模式                  |