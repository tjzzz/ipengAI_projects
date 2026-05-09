# WorkBuddy Skills

芃芃工作室数据分析工作流所需的 AI Agent 技能包。

## 技能目录

| 技能 | 版本 | 说明 |
|------|------|------|
| [data-agent](./skills/data-agent/) | v1.1.0 | 数据分析专家 — 项目初始化、报告撰写、AI检测、降重、飞书登记 |
| [turnitin-ai-checker](./skills/turnitin-ai-checker/) | — | Turnitin AI 检测 — 文本分析与 AI 率预测 |
| [ai-text-humanizer-api](./skills/ai-text-humanizer-api/) | v1.0.0 | 付费 API 降重 — 调用 ai-text-humanizer.com，作为三级降重策略的 L3 手段 |

## 降重策略

```
L1: turnitin-ai-checker humanize.py（免费）
  ↓ AI率 < 20% → ✅ 完成
  ↓ AI率 ≥ 20%
L2: 手动拆分长句 + 简化词汇（免费）
  ↓ AI率 < 20% → ✅ 完成
  ↓ AI率 ≥ 20%
L3: ai-text-humanizer-api（付费API，仅发高风险段落）
  ↓
最终验证
```

每级**仅执行一次**，不反复迭代。L3 后仍不达标则输出手工修改指引。

## 使用方式

技能通过 WorkBuddy 的 `@skill:xxx` 语法加载：

```
@skill:data-agent           # 加载数据分析专家
@skill:turnitin-ai-checker  # 加载 AI 检测
@skill:ai-text-humanizer-api # 加载付费降重 API
```

## 依赖

- **lark-cli** — 飞书多维表格登记（`npm install -g @larksuite/cli`）
- **antiword** — `.doc` 文件读取（macOS 已预装或 `brew install antiword`）
- **PyMuPDF** — `.pdf` 文件读取（自动安装）
- **python-pptx** — `.pptx` 文件读取（自动安装）

`data-agent` 的 `scripts/setup_env.py --check` 可自动检查并安装所有依赖。
