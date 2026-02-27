# GTOS — 洋葱式自动代码生成 + 插件扩展

最小可运行版本：核心执行闭环 + 插件机制 + 技能存储。

## 运行

在项目根目录 `e:\aiApi\goaptOS` 下执行：

```cmd
pip install -e .
python -m gtos.main
```

或直接双击/运行：

```cmd
run.cmd
```

前端监控面板（React + TailwindCSS + Ant Design）：

```cmd
cd dashboard-ui
npm install
npm run dev
```

页面会读取 `dashboard-ui/public/data/*.json`（构建/启动前会自动从 `data/` 同步）。

Web Chat API（本地）：

```cmd
run_web_api.cmd
```

默认地址 `http://127.0.0.1:8000`，前端会通过 Vite 代理 `/api/chat` 与其交互。

## 配置

在项目根目录的 **`config.json`** 中自行修改配置，无需改代码。

| 配置项 | 说明 |
|--------|------|
| `paths.skills_file` | 技能存储 JSON 路径（相对项目根或绝对路径） |
| `paths.sqlite_db` | SQLite 数据库路径 |
| `executor.max_fix_rounds` | 执行失败时最多自动修复轮数 |
| `executor.timeout_seconds` | 单次代码执行超时（秒） |
| `plugins.enabled` | 启用的插件列表：`logger` / `feedback` / `skill` / `agent` / `llm_optimizer` |
| `plugins.skill.recent_count` | 技能插件注入的最近成功任务条数 |
| `plugins.skill.retrieval_top_k` | 向量/关键词检索返回条数 |
| `plugins.skill.ab_test.*` | A/B 实验：`control`(不注入) vs `treatment`(注入)；输出 `skill_ab_metrics.json` |
| `plugins.llm_optimizer.refine` | 是否在 pre 阶段用 LLM 优化任务描述 |
| `memory.vector_store.enabled` | 是否启用技能向量/关键词存储 |
| `memory.vector_store.backend` | `keyword`（无依赖）或 `chroma`（需 pip install chromadb） |
| `memory.vector_store.embedding.*` | `backend=chroma` 时可单独配置 embedding（`model/base_url/api_key`） |
| `executor.use_planner` | 是否走 DAG 规划（当前单节点仍为单任务） |
| `executor.dag_parallel` | DAG 多节点时是否同层并行 |
| `executor.dag_max_workers` | 并行时最大线程数 |
| `executor.node_retry_count` | 节点级额外重试次数（DAG 模式） |
| `executor.dag_fail_policy` | `stop` / `skip` / `continue` 失败策略 |
| `self_cognition + planner` | 风险高时自动降级执行策略（禁并行、`fail_policy=stop`） |
| `analytics.runs_file` | 任务运行事件日志（JSONL）路径 |
| `analytics.metrics_file` | 聚合指标输出路径 |
| `optimization.mode` | `suggest` 仅建议 / `apply` 自动应用策略 |
| `optimization.*` | 基于历史指标自动调整执行策略（并行/重试/失败策略/refine） |
| `self_cognition.mode` | `off` / `advise` / `enforce` |
| `self_cognition.profile_file` | 能力画像统计文件 |
| `self_cognition.blocked_keywords` | 命中后直接拒绝执行 |
| `self_cognition.high_risk_keywords` | 命中后告警（`advise`）或拒绝（`enforce`） |
| `self_cognition.dynamic.*` | 基于 runs 历史的动态风险调节（失败率/修复轮次） |
| `visualization.*` | 生成“上帝视角”快照（`dashboard.json` + `dashboard.md`） |
| `logging.level` | 日志级别：`DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `default_task` | 默认任务描述（`main` 无参数时的任务） |
| `llm.provider` | 当前支持 `openai_compatible` |
| `llm.base_url` | OpenAI 兼容接口地址（例如 `https://api.openai.com/v1`） |
| `llm.model` | 代码生成/修复模型 |
| `llm.tokenizer_model` | 分词模型（可与 `model` 独立配置，用于 token 估算与截断） |
| `llm.api_key_env` / `llm.api_key` | API Key 来源（优先 `api_key`，否则读取环境变量） |
| `llm.max_input_tokens` / `llm.max_output_tokens` | 输入截断和输出长度控制 |

指定配置文件路径：`python -m gtos.main --config /path/to/config.json`，或设置环境变量 `GTOS_CONFIG=/path/to/config.json`。

## 架构（自外而内）

- **监控/日志插件层** → LoggerPlugin（计时、日志）
- **智能增强插件层** → LLMOptimizerPlugin（可选 LLM 优化 prompt）
- **多任务/Agent 插件层** → AgentPlugin（预留）
- **技能复用层** → SkillPlugin（pre 检索相似技能注入 prompt，post 写入 VectorStore）
- **任务规划层** → planner.plan_to_dag / dag_runner.run_dag（DAG + 可选并行）
- **执行闭环层** → CodeExecutor（生成 → 执行 → 自动修复）
- **核心执行引擎** → CodeExecutor + SkillStore + Memory（VectorStore 关键词/Chroma）

## 连接真实 LLM

1. 配置 `config.json` 中的 `llm.base_url`、`llm.model`。
2. 设置 API Key：`set OPENAI_API_KEY=...`（或直接写 `llm.api_key`）。
3. 运行 `python -m gtos.main --task "写一个 Python 脚本输出当前时间"`。

### Chroma + 独立 Embedding 模型示例

```json
{
  "memory": {
    "vector_store": {
      "backend": "chroma",
      "embedding": {
        "enabled": true,
        "provider": "openai_compatible",
        "model": "text-embedding-3-small"
      }
    }
  }
}
```
