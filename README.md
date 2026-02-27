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

## 配置

在项目根目录的 **`config.json`** 中自行修改配置，无需改代码。

| 配置项 | 说明 |
|--------|------|
| `paths.skills_file` | 技能存储 JSON 路径（相对项目根或绝对路径） |
| `paths.sqlite_db` | SQLite 数据库路径 |
| `executor.max_fix_rounds` | 执行失败时最多自动修复轮数 |
| `executor.timeout_seconds` | 单次代码执行超时（秒） |
| `plugins.enabled` | 启用的插件列表：`logger` / `skill` / `agent` / `llm_optimizer` |
| `plugins.skill.recent_count` | 技能插件注入的最近成功任务条数 |
| `plugins.skill.retrieval_top_k` | 向量/关键词检索返回条数 |
| `plugins.llm_optimizer.refine` | 是否在 pre 阶段用 LLM 优化任务描述 |
| `memory.vector_store.enabled` | 是否启用技能向量/关键词存储 |
| `memory.vector_store.backend` | `keyword`（无依赖）或 `chroma`（需 pip install chromadb） |
| `memory.vector_store.embedding.*` | `backend=chroma` 时可单独配置 embedding（`model/base_url/api_key`） |
| `executor.use_planner` | 是否走 DAG 规划（当前单节点仍为单任务） |
| `executor.dag_parallel` | DAG 多节点时是否同层并行 |
| `executor.dag_max_workers` | 并行时最大线程数 |
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
