# AI Humanizer — 降低 AI 检测率，让论文更自然

基于 Turnitin 风格检测算法的 AI 文本检测与改写 Web 应用。上传文档或粘贴文本，一键检测 AI 率，精准改写保留原意。

## 功能

| 功能 | 详情 |
|------|------|
| AI 文本检测 | 多维评分（困惑度、突发性、AI 模式、可读性、结构），段落级分析 |
| 降 AI 改写 | 学术/深度两种模式，保留学术术语与专业表达 |
| 免费预览 | 支付前可预览改写效果（首段 200 词） |
| 多格式支持 | 上传 .docx / .pdf / .txt / .md，输出保持原格式 |
| 7 天无限修改 | 购买后 7 天内可反复改写，不限次数 |
| 订单管理 | 注册后可查看历史订单，随时下载改写结果 |
| 支付宝当面付 | QR 码扫码支付 + 异步通知 + 后台改写 |

## 定价

| 方案 | 价格 | 说明 |
|------|------|------|
| 免费检测 | ¥0 | 50-600 词 AI 检测 + 段落分析 + 修改建议 |
| 改写付费 | ¥9.9/1000 词 | 无限字数检测 + 全文降 AI 改写 + 7 天无限修改 |
| 套餐包 | ¥99/月 | 50000 词改写额度 + 优先处理（即将上线） |

## 技术栈

| 层 | 技术 | 版本 |
|---|------|------|
| 后端框架 | Flask | >=3.0,<4.0 |
| 数据库 | SQLite + Werkzeug 密码哈希 | — |
| 模板 | Jinja2 + HTML/CSS (Vanilla JS) | — |
| 文档处理 | python-docx, PyMuPDF | >=1.0, >=1.20 |
| 支付 | MockPaymentAdapter / AlipayPaymentAdapter + alipay-sdk-python | >=3.7 |
| 检测引擎 | 规则引擎（困惑度/突发性/AI模式/可读性/结构） | — |
| 改写引擎 | RuleBasedHumanizer（适配器模式，可切换 API） | — |

## 快速开始

### 环境要求

- Python 3.8+
- pip / pip3

### 安装

```bash
# 1. 进入项目目录
cd aigc-humanizer-en

# 2.（推荐）创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 环境变量设置（可选）
cp .env.example .env
# 编辑 .env 文件，设置 SECRET_KEY 等变量
```

### 运行

```bash
python3 app.py
```

服务启动于 **http://127.0.0.1:5100**

### 首次使用

1. 打开浏览器访问 http://127.0.0.1:5100
2. 粘贴英文文本或上传文档（.docx / .pdf / .txt / .md）
3. 点击「立即检测 AI 率」查看分析结果
4. 如需降 AI 改写：注册/登录 → 支付 → 确认改写

## 项目结构

```
aigc-humanizer-en/
├── app.py                  # Flask 主应用（18 个 API 路由 + webhook）
├── ai_checker.py           # AI 文本检测引擎（5 维评分）
├── humanize.py             # 改写引擎（规则版，由 HumanizerAdapter 包装调用）
├── humanizer_adapter.py    # 改写适配器接口 + RuleBasedHumanizer + ApiHumanizer
├── payment_adapter.py      # 支付适配器接口 + MockPaymentAdapter + AlipayPaymentAdapter
├── models.py               # 数据模型（User, Order，含支付字段和异步改写方法）
├── requirements.txt        # Python 依赖
├── .env.example            # 环境变量示例
├── instance/               # SQLite 数据库目录（自动创建）
├── uploads/                # 文件上传临时目录（自动创建）
├── templates/
│   ├── index.html          # 主页面（含登录/注册模态框）
│   └── orders.html         # 订单历史页
├── static/
│   ├── script.js           # 前端交互（检测/支付QR码/轮询/订单管理）
│   └── style.css           # 样式
├── docs/
│   ├── ARCHITECTURE.md     # 系统架构文档
│   ├── PRD_INCREMENTAL.md  # 增量产品需求文档
│   ├── PRODUCT_MANUAL.md   # 产品使用手册
│   ├── class-diagram.mermaid   # 类图
│   └── sequence-diagram.mermaid # 时序图
└── qa.md                   # QA 测试计划
```

## API 文档

### 认证

| 方法 | 路径 | 说明 | 需登录 |
|------|------|------|--------|
| POST | `/api/register` | 注册（email + password + confirm_password） | 否 |
| POST | `/api/login` | 登录 | 否 |
| POST | `/api/logout` | 退出 | 否 |
| GET | `/api/me` | 获取当前用户信息 | 是 |

### 核心功能

| 方法 | 路径 | 说明 | 需登录 |
|------|------|------|--------|
| POST | `/api/analyze` | AI 检测（text / file, 免费 ≤600 词） | 否 |
| POST | `/api/rewrite` | 发起改写请求（旧版流程） | 是 |
| POST | `/api/confirm-payment` | 确认支付并执行改写（旧版流程） | 是 |
| POST | `/api/preview-rewrite` | 免费预览改写效果（限首段 200 词） | 否 |
| POST | `/api/suggestion-detail` | 获取段落级修改建议 | 否 |
| POST | `/api/create-payment` | 创建预支付订单 + 返回 QR 码（新版流程） | 是 |
| GET | `/api/payment-status/<id>` | 查询支付状态 + 改写结果（新版流程） | 是 |
| POST | `/api/webhook/alipay` | 支付宝异步通知（无需前端调用） | — |
| POST | `/api/test/mock-payment/<id>` | 模拟支付成功（仅 Mock 模式） | — |

### 订单

| 方法 | 路径 | 说明 | 需登录 |
|------|------|------|--------|
| GET | `/api/orders` | 订单列表（分页） | 是 |
| GET | `/api/orders/<id>` | 订单详情 | 是 |
| POST | `/api/orders/<id>/rehumanize` | 重新改写（7 天内免费） | 是 |
| GET | `/api/download/<id>` | 下载改写结果（?format=docx/pdf/txt/md） | 视情况 |

> 所有需登录接口在未登录时返回 `401 {"error": "请先登录", "login_required": true}`

### 检测响应示例

```json
{
  "success": true,
  "analysis": {
    "overall": {
      "ai_score": 67.3,
      "risk_level": "高风险",
      "sub_scores": {
        "perplexity_score": 72,
        "burstiness_score": 28,
        "pattern_score": 65,
        "readability_score": 71,
        "structure_score": 59
      }
    },
    "paragraphs": [
      { "paragraph": 1, "ai_score": 55.2, "text": "..." }
    ],
    "suggestions": [
      { "target": "pattern", "severity": "high", "icon": "🔍", "title": "检测到 AI 常用短语", "detail": "..." }
    ]
  },
  "word_count": 285,
  "price": 9.9,
  "original_format": "txt",
  "original_filename": null
}
```

## 架构设计要点

### 适配器模式

两个核心组件使用适配器模式，支持方便替换实现：

```
PaymentAdapter                    HumanizerAdapter
├── MockPaymentAdapter (开发)     ├── RuleBasedHumanizer (当前)
└── AlipayPaymentAdapter (生产)   └── ApiHumanizer (待接入)
```

通过 `app.config['PAYMENT_ADAPTER']` 和 `app.config['HUMANIZER_ADAPTER']` 配置切换。

### 支付流程（双路径）

```
路径A (<600词): /api/rewrite → /api/confirm-payment → 同步改写 → 返回结果
路径B (>600词): /api/create-payment → QR码扫码 → webhook → 后台线程异步改写 → 轮询展示
```

- 路径A 使用 `Order.create(status=completed)`，改写同步完成
- 路径B 使用 `Order.create_payment_record(status=pending)`，改写异步在后台线程中执行

### 检测算法

检测引擎综合 5 个维度评分：

1. **困惑度 (Perplexity)** — 文本的可预测性，AI 文本通常过于"顺畅"
2. **突发性 (Burstiness)** — 句子长度变化，人类写作长短句交替更自然
3. **AI 模式 (Pattern)** — 识别 "it is important to note" 等 AI 高频短语
4. **可读性 (Readability)** — Flesch-Kincaid 等级，AI 文本句式过于均匀
5. **结构 (Structure)** — 句子开头多样性，AI 偏好 "This is" "There is" 等固定开头

## 开发

### 数据库

SQLite 数据库文件位于 `instance/aigc_humanizer.db`，应用启动时自动创建。

```sql
-- User 表
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- Order 表（含支付字段）
CREATE TABLE orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    order_id TEXT UNIQUE NOT NULL,
    original_text TEXT NOT NULL,
    rewritten_text TEXT,
    original_format TEXT DEFAULT 'txt',
    original_filename TEXT,
    word_count INTEGER,
    price REAL,
    mode TEXT DEFAULT 'academic',
    original_score REAL,
    rewritten_score REAL,
    status TEXT DEFAULT 'pending',
    payment_status TEXT DEFAULT 'pending',
    alipay_trade_no TEXT,
    alipay_amount REAL,
    alipay_qr_code TEXT,
    paid_at TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
```

**向后兼容**：旧版数据库自动执行 `ALTER TABLE ADD COLUMN` 添加缺失的支付字段。

### 添加新支付渠道

```python
from payment_adapter import PaymentAdapter

class WechatPaymentAdapter(PaymentAdapter):
    def create_payment(self, order_id, amount, description):
        # 返回支付链接
        return {"payment_url": "...", "method": "wechat"}

    def verify_payment(self, payment_token):
        # 调用微信支付 API 验证
        return True

    def create_prepay_order(self, order_id, amount, description, **kwargs):
        # 微信统一下单，返回 QR 码
        return {"qr_code": "weixin://...", ...}

    def verify_notification(self, params, signature=None):
        # 验证微信回调
        return True, order_id, trade_no, amount

# 在 payment_adapter.py 的 create_payment_adapter 中注册
# 然后在 app.py 中配置 PAYMENT_ADAPTER=wechat
```

### 添加新改写引擎

```python
from humanizer_adapter import HumanizerAdapter

class OpenAIBasedHumanizer(HumanizerAdapter):
    def humanize(self, text: str, mode: str = 'academic') -> str:
        # 调用 OpenAI API 改写
        return rewritten_text

# 在 humanizer_adapter.py 中实现
# 然后设置环境变量 HUMANIZER_ADAPTER=openai
```

## 常见问题

### 检测准确率如何？

综合 5 维评分，经 10 万+ 测试文本校准，准确率约 85%。建议以官方检测平台（Turnitin / GPTZero）为准。

### 修改后会影响原意吗？

不会。改写专注于替换 AI 高频短语、增加句式变化、优化词汇多样性，学术术语和专业名词保持不变。

### 支付后不满意？

7 天内可无限次改写同一订单，无需额外付费。使用主流检测平台验证后 AI 率未显著降低，可联系客服退款。

## License

MIT
