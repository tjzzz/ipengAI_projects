# AI Humanizer - 技术架构文档

> **版本**: v1.0 | **日期**: 2026-05-28 | **状态**: 已整合
>
> 整合来源：ARCHITECTURE.md + product-doc.md 第3章 + class-diagram.mermaid + sequence-diagram.mermaid

---

## 目录

- [1. 系统架构总览](#1-系统架构总览)
- [2. 技术栈](#2-技术栈)
- [3. 架构模式](#3-架构模式)
- [4. 数据模型](#4-数据模型)
- [5. API 接口](#5-api-接口)
- [6. 核心流程](#6-核心流程)
- [7. 检测引擎](#7-检测引擎)
- [8. 改写引擎](#8-改写引擎)
- [9. 文件结构](#9-文件结构)
- [10. 共享约定](#10-共享约定)
- [11. 任务列表](#11-任务列表)

---

## 1. 系统架构总览

```mermaid
architecture-beta
    group frontend[Client Browser]
        service index[HTML/CSS/JS] in frontend
        service orders[Orders Page] in frontend

    group backend[Flask Server]
        service routes[app.py Routes] in backend
        service checker[ai_checker.py] in backend
        service humanizer[humanizer_adapter.py] in backend
        service payment[payment_adapter.py] in backend
        service models[models.py] in backend

    group storage[Data Layer]
        service sqlite[(SQLite DB)] in storage
        service uploads[Uploads Dir] in storage

    group external[External]
        service alipay[Alipay Gateway] in external

    index:B -- N:orders
    index:S --> N:routes
    orders:S --> N:routes
    routes:S --> N:checker
    routes:S --> N:humanizer
    routes:S --> N:payment
    routes:S --> N:models
    models:S --> N:sqlite
    payment:E --> W:alipay
    routes:W --> E:uploads
```

### 分层架构

```mermaid
flowchart TB
    subgraph Frontend["📱 前端层 (HTML/CSS/JS)"]
        A[index.html 主页]
        B[orders.html 订单页]
        C[script.js 交互逻辑]
        D[style.css 样式]
    end

    subgraph API["🔌 API 路由层 (app.py)"]
        E[Auth Routes]
        F[Analysis Routes]
        G[Rewrite Routes]
        H[Payment Routes]
        I[Order Routes]
        J[Download Routes]
    end

    subgraph Adapter["🔧 适配器层"]
        K[PaymentAdapter]
        L[HumanizerAdapter]
    end

    subgraph Core["⚙️ 核心引擎"]
        M[AI 检测引擎\nai_checker.py]
        N[规则改写引擎\nhumanize.py]
    end

    subgraph Data["💾 数据层"]
        O[User 模型]
        P[Order 模型]
    end

    subgraph Storage["🗄️ 存储"]
        Q[(SQLite DB)]
        R[uploads/]
    end

    Frontend -->|HTTP JSON| API
    API --> K
    API --> L
    API --> M
    API --> O
    API --> P
    Adapter --> Core
    Data --> Q
    API --> R
```

---

## 2. 技术栈

### 依赖矩阵

```mermaid
flowchart LR
    subgraph Python["Python 后端"]
        Flask[Flask 3.x<br>Web 框架]
        Werkzeug[Werkzeug 3.x<br>密码哈希+Session]
        Docx[python-docx<br>DOCX 读写]
        PyMuPDF[PyMuPDF<br>PDF 读写]
        AlipaySDK[alipay-sdk-python<br>支付宝当面付]
        SQLite[sqlite3<br>内置数据库]
    end

    subgraph JS["前端"]
        VanillaJS[Vanilla JS<br>原生 JavaScript]
        QRCode[qrcode.js<br>二维码渲染]
        Jinja2[Jinja2<br>模板引擎]
    end
```

### 选型理由

| 库/框架 | 版本 | 用途 | 选型理由 |
|---------|------|------|----------|
| Flask | >=3.0,<4.0 | Web 框架 | 保持现有栈，零迁移成本 |
| Werkzeug | >=3.0,<4.0 | 密码哈希 + session | Flask 内置依赖 |
| python-docx | >=1.0,<2.0 | .docx 读写 | 标准 DOCX 处理库 |
| PyMuPDF | >=1.20,<2.0 | .pdf 读写 | 高性能 PDF 处理 |
| alipay-sdk-python | >=3.7,<4.0 | 支付宝当面付 | 官方 SDK |
| sqlite3 | Python 内置 | 数据库 | 零依赖，适合单机 |
| Vanilla JS | — | 前端 | 无框架依赖，轻量 |

---

## 3. 架构模式

### 3.1 核心设计模式

**模式一：MVC 分层**
- **Model**: `models.py` — User、Order 数据模型
- **View**: `templates/` — Jinja2 模板 (index.html, orders.html)
- **Controller**: `app.py` — 路由层，编排业务逻辑

**模式二：适配器模式 (Strategy)**
- `PaymentAdapter` — 统一支付接口，Mock / Alipay 可替换
- `HumanizerAdapter` — 统一改写接口，RuleBased / API 可替换

```mermaid
flowchart TB
    subgraph Payment["支付适配器"]
        PA[PaymentAdapter<br>抽象接口]
        MP[MockPaymentAdapter<br>开发测试]
        AP[AlipayPaymentAdapter<br>生产环境]
    end

    subgraph Humanizer["改写适配器"]
        HA[HumanizerAdapter<br>抽象接口]
        RH[RuleBasedHumanizer<br>当前使用]
        AH[ApiHumanizer<br>未来扩展]
    end

    App[Flask App] -.->|uses| PA
    PA <|-- MP
    PA <|-- AP
    App -.->|uses| HA
    HA <|-- RH
    HA <|-- AH
```

**模式三：异步后台任务**
- 支付 Webhook 回调中使用 `threading.Thread(daemon=True)` 异步执行改写
- 不阻塞支付宝回调响应，保证支付通知及时返回 "success"

### 3.2 核心技术挑战与应对

| 挑战 | 应对方案 |
|------|----------|
| 用户认证 | `werkzeug.security` 哈希密码 + Flask session |
| 订单持久化 | SQLite 存储，支持历史查询和 7 天重下载 |
| 格式保持输出 | python-docx 写 docx, PyMuPDF 写 pdf, 直接写 md/txt |
| 支付可扩展 | 适配器模式 — MockPaymentAdapter + AlipayPaymentAdapter |
| 改写引擎可替换 | 适配器模式 — 统一 HumanizerAdapter 接口 |
| 异步改写 | `threading.Thread` 后台执行，不阻塞 webhook |

---

## 4. 数据模型

### 4.1 数据库 ER 图

```mermaid
erDiagram
    USERS {
        int id PK
        text email UK
        text password_hash
        text created_at
    }

    ORDERS {
        int id PK
        int user_id FK
        text order_id UK
        text original_text
        text rewritten_text
        text original_format
        text original_filename
        int word_count
        real price
        text mode
        real original_score
        real rewritten_score
        text status
        text payment_status
        text alipay_trade_no
        real alipay_amount
        text alipay_qr_code
        text paid_at
        text created_at
        text expires_at
    }

    USERS ||--o{ ORDERS : "has"
```

### 4.2 类图

```mermaid
classDiagram
    class User {
        +int id
        +str email
        +str password_hash
        +str created_at
        +create(email, password) User
        +get_by_email(email) User|None
        +get_by_id(user_id) User|None
        +verify_password(email, password) User|None
    }

    class Order {
        +int id
        +int user_id
        +str order_id
        +str original_text
        +str rewritten_text
        +str original_format
        +str original_filename
        +int word_count
        +float price
        +str mode
        +float original_score
        +float rewritten_score
        +str status
        +str payment_status
        +str alipay_trade_no
        +float alipay_amount
        +str alipay_qr_code
        +str paid_at
        +str created_at
        +str expires_at
        +create(...) Order
        +get_by_user_id(user_id, page, per_page) tuple
        +get_by_order_id(order_id) Order|None
        +update_rewrite(order_id, text, score) None
        +create_payment_record(...) Order
        +save_qr_code(order_id, qr_code) None
        +mark_paid(order_id, trade_no, paid_at) None
        +update_result(order_id, text, score) None
        +get_payment_status(order_id) dict
        +expire_old_orders(max_age_minutes) None
    }

    class PaymentAdapter {
        <<abstract>>
        +create_payment(order_id, amount, description) dict*
        +verify_payment(payment_token) bool*
        +create_prepay_order(order_id, amount, description) dict
        +verify_notification(params, signature) tuple
        +query_payment(order_id) dict
    }

    class MockPaymentAdapter {
        +create_payment(...) dict
        +verify_payment(...) bool
        +create_prepay_order(...) dict
        +verify_notification(...) tuple
        +query_payment(...) dict
    }

    class AlipayPaymentAdapter {
        +str app_id
        +str pid
        +alipay SDK client
        +create_payment(...) dict
        +verify_payment(...) bool
        +create_prepay_order(...) dict
        +verify_notification(...) tuple
        +query_payment(...) dict
    }

    class HumanizerAdapter {
        <<abstract>>
        +humanize(text, mode) str*
    }

    class RuleBasedHumanizer {
        +humanize(text, mode) str
    }

    class ApiHumanizer {
        +humanize(text, mode) str
    }

    User "1" --> "*" Order : has
    PaymentAdapter <|-- MockPaymentAdapter : implements
    PaymentAdapter <|-- AlipayPaymentAdapter : implements
    HumanizerAdapter <|-- RuleBasedHumanizer : implements
    HumanizerAdapter <|-- ApiHumanizer : implements
```

### 4.3 Schema SQL

```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    order_id TEXT UNIQUE NOT NULL,
    original_text TEXT NOT NULL,
    rewritten_text TEXT,                -- NULL when payment pending
    original_format TEXT DEFAULT 'txt',
    original_filename TEXT,
    word_count INTEGER,
    price REAL,
    mode TEXT DEFAULT 'academic',
    original_score REAL,
    rewritten_score REAL,
    status TEXT DEFAULT 'pending',       -- pending/processing/completed/expired
    payment_status TEXT DEFAULT 'pending',  -- pending/paid/expired
    alipay_trade_no TEXT,
    alipay_amount REAL,
    alipay_qr_code TEXT,
    paid_at TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
```

> **向后兼容**：`Order.init_table()` 在旧数据库上自动执行 `ALTER TABLE ADD COLUMN` 添加缺失字段。

---

## 5. API 接口

### 5.1 接口总览

```mermaid
flowchart LR
    subgraph Auth["认证"]
        A1[POST /api/register]
        A2[POST /api/login]
        A3[POST /api/logout]
        A4[GET /api/me]
    end

    subgraph Analysis["检测"]
        B1[POST /api/analyze]
        B2[POST /api/suggestion-detail]
        B3[POST /api/preview-rewrite]
    end

    subgraph Payment["支付"]
        C1[POST /api/rewrite]
        C2[POST /api/confirm-payment]
        C3[POST /api/create-payment]
        C4[GET /api/payment-status/:id]
        C5[POST /api/webhook/alipay]
        C6[POST /api/test/mock-payment/:id]
    end

    subgraph Order["订单"]
        D1[GET /api/orders]
        D2[GET /api/orders/:id]
        D3[POST /api/orders/:id/rehumanize]
    end

    subgraph Download["下载"]
        E1[GET /api/download/:id]
    end
```

### 5.2 接口详情

#### 认证接口

| 方法 | 路径 | 请求体 | 响应 | 说明 |
|------|------|--------|------|------|
| POST | `/api/register` | `{email, password, confirm_password}` | `{success, user}` 或 `{error}` | 邮箱注册，密码 ≥6 位 |
| POST | `/api/login` | `{email, password}` | `{success, user}` 或 `{error}` | 邮箱密码登录 |
| POST | `/api/logout` | — | `{success}` | 清除 session |
| GET | `/api/me` | — | `{user}` 或 401 | 获取当前用户 |

#### 检测接口

| 方法 | 路径 | 请求体 | 响应 | 说明 |
|------|------|--------|------|------|
| POST | `/api/analyze` | `{text}` 或 multipart file | `{analysis, word_count, price}` | AI 检测，超限返回 413 |
| POST | `/api/suggestion-detail` | `{text, paragraph_index}` | 段落级分析+建议 | 逐段详细建议 |
| POST | `/api/preview-rewrite` | `{text}` | 首段改写预览 | 免费，≤200 词 |

#### 支付接口

| 方法 | 路径 | 请求体 | 响应 | 说明 |
|------|------|--------|------|------|
| POST | `/api/rewrite` | `{text, mode}` | `{order: {order_id, price}}` | 旧版改写（<600 词） |
| POST | `/api/confirm-payment` | `{payment_token}` | `{original, rewritten, improvement}` | 旧版确认支付+同步改写 |
| POST | `/api/create-payment` | `{text, mode}` | `{order: {order_id, qr_code}}` | 新版创建 QR 支付 |
| GET | `/api/payment-status/<id>` | — | `{payment_status, status, rewritten?}` | 轮询支付/改写状态 |
| POST | `/api/webhook/alipay` | 支付宝签名参数 | `"success"` / `"fail"` | 支付宝异步通知 |
| POST | `/api/test/mock-payment/<id>` | — | `{success}` | Mock 模拟支付 |

#### 订单接口

| 方法 | 路径 | 请求体 | 响应 | 说明 |
|------|------|--------|------|------|
| GET | `/api/orders` | `?page=&per_page=` | `{orders, total, page, pages}` | 分页订单列表 |
| GET | `/api/orders/<id>` | — | `{order}` 或 404/403 | 订单详情 |
| POST | `/api/orders/<id>/rehumanize` | `{mode}` | 重新改写结果 或 410 | 7 天内免费重改写 |
| GET | `/api/download/<id>` | `?format=docx\|pdf\|txt\|md` | File download | 格式保持下载 |

---

## 6. 核心流程

### 6.1 渐进式交互流程（核心路径）

```mermaid
sequenceDiagram
    participant User as 用户
    participant Browser as 浏览器
    participant App as Flask app.py
    participant AI as ai_checker.py
    participant PAdapter as PaymentAdapter
    participant Alipay as 支付宝网关
    participant DB as SQLite
    participant Thread as 后台线程

    Note over User, Thread: ① 检测 → 展示结果（零门槛）
    User->>Browser: 上传文件/粘贴文本
    Browser->>App: POST /api/analyze
    App->>App: extract_text + 分析
    App-->>Browser: {analysis, text, word_count, price}
    Browser->>Browser: 展示完整检测结果（AI率+分析+建议）
    Note right of Browser: 匿名用户全程可见，无需登录

    Note over User, Thread: ② 用户主动点击改写
    User->>Browser: 点击改写按钮
    alt 未登录
        Browser->>Browser: 弹出登录/注册弹窗
        User->>Browser: 登录/注册
        Browser->>App: POST /api/login (或 /api/register)
        App-->>Browser: {user}
    end

    alt 免费改写 (price === 0)
        Browser->>App: POST /api/rewrite {text, mode}
        App->>App: humanize + analyze
        App-->>Browser: {original, rewritten, improvement}
        Browser->>Browser: 展示改写对比结果

    else 付费改写 (price > 0)
        Note over User, Thread: ③ 创建支付订单 + 二维码即显示
        Browser->>App: POST /api/create-payment {text, mode}
        App->>DB: Order.create_payment_record(status=pending)
        App->>PAdapter: create_prepay_order(order_id, amount)
        PAdapter-->>App: {qr_code, order_id, expires_in}
        App->>DB: Order.save_qr_code(qr_code)
        App-->>Browser: {order: {order_id, price, qr_code}}
        Browser->>Browser: 立即渲染二维码 + 3s 轮询

        Note over User, Thread: ④ 用户扫码支付
        User->>Browser: 扫码支付
        Browser->>Alipay: 支付宝付款

        Note over User, Thread: ⑤ 支付宝异步通知
        Alipay->>App: POST /api/webhook/alipay
        App->>PAdapter: verify_notification(params, sign)
        PAdapter-->>App: (is_valid=True, order_id, trade_no)
        App->>DB: Order.mark_paid(order_id, trade_no)
        App->>App: 启动后台改写线程
        App-->>Alipay: "success"

        Note over Thread, DB: ⑥ 后台异步改写
        Thread->>App: humanizer.humanize(text)
        App-->>Thread: humanized_text
        Thread->>DB: Order.update_result(rewritten_text, scores)

        Note over User, DB: ⑦ 前端轮询检测完成
        loop 每3秒轮询
            Browser->>App: GET /api/payment-status/<id>
            App-->>Browser: {status: "processing" / "completed"}
        end
        Browser->>Browser: 自动展示改写对比结果
    end
```

### 6.2 旧版模态框支付流程（<600 词，兼容路径）

```mermaid
sequenceDiagram
    participant User as 用户
    participant Browser as 浏览器
    participant App as Flask app.py
    participant AI as ai_checker.py
    participant HAdapter as HumanizerAdapter
    participant PAdapter as PaymentAdapter
    participant DB as SQLite

    Note over User, DB: ① 文本检测
    User->>Browser: 粘贴文本/上传文件
    Browser->>App: POST /api/analyze
    App->>AI: analyze_text(text)
    AI-->>App: {ai_score, ...}
    App-->>Browser: {analysis, original_format, ...}
    Browser->>Browser: 显示检测结果

    Note over User, DB: ② 发起改写+支付
    User->>Browser: 点击「自动改写」→ 支付模态框
    Browser->>App: POST /api/rewrite {text, mode}
    App->>App: 计算价格，生成 order_id
    App-->>Browser: {order_id, price, word_count}

    User->>Browser: 确认支付
    Browser->>App: POST /api/confirm-payment {payment_token: "PAY-..."}
    App->>PAdapter: verify_payment(payment_token)
    PAdapter-->>App: True
    App->>HAdapter: humanize(text, mode)
    HAdapter-->>App: humanized_text
    App->>AI: analyze_text(humanized)
    AI-->>App: {ai_score, ...}
    App->>DB: Order.create(status=completed)
    DB-->>App: OK
    App-->>Browser: {original, rewritten, improvement}

    Note over User, DB: ③ 格式保持下载
    User->>Browser: 点击「下载」
    Browser->>App: GET /api/download/<order_id>?format=docx
    App->>DB: SELECT * FROM orders WHERE order_id=?
    DB-->>App: order row
    App->>App: 根据格式生成对应文件
    App-->>Browser: 文件下载
```

### 6.3 用户注册/登录流程

```mermaid
sequenceDiagram
    participant User as 用户
    participant Browser as 浏览器
    participant App as Flask app.py
    participant DB as SQLite
    participant Werkzeug as werkzeug.security

    rect rgb(240, 248, 255)
        Note over User, Werkzeug: 注册流程
        User->>Browser: 填写注册表单
        Browser->>Browser: 前端校验密码一致性+长度
        Browser->>App: POST /api/register
        App->>App: 校验邮箱格式+密码>6位
        App->>DB: SELECT id FROM users WHERE email=?
        DB-->>App: None（邮箱未注册）
        App->>Werkzeug: generate_password_hash(password, method='pbkdf2:sha256')
        Werkzeug-->>App: password_hash
        App->>DB: INSERT INTO users (email, password_hash, created_at)
        DB-->>App: new_user_id
        App->>App: session['user_id'] = new_user_id
        App-->>Browser: {success, user: {id, email}}
        Browser->>Browser: 更新导航栏
    end

    rect rgb(255, 248, 240)
        Note over User, Werkzeug: 登录流程
        User->>Browser: 填写登录表单
        Browser->>App: POST /api/login
        App->>DB: SELECT * FROM users WHERE email=?
        DB-->>App: user row
        App->>Werkzeug: check_password_hash(user.password_hash, password)
        Werkzeug-->>App: True
        App->>App: session['user_id'] = user.id
        App-->>Browser: {success, user: {id, email}}
        Browser->>Browser: 更新导航栏
    end
```

### 6.4 订单历史 + 7 天免费重改写

```mermaid
sequenceDiagram
    participant User as 用户
    participant Browser as 浏览器
    participant App as Flask app.py
    participant DB as SQLite

    User->>Browser: 点击「订单历史」
    Browser->>App: GET /orders
    App->>App: 检查 session['user_id']
    alt 未登录
        App-->>Browser: 渲染 orders.html (needs_login=true)
    else 已登录
        App->>DB: SELECT * FROM orders WHERE user_id=? ORDER BY created_at DESC LIMIT 10
        DB-->>App: [Order, ...]
        App->>DB: SELECT COUNT(*) FROM orders WHERE user_id=?
        DB-->>App: total_count
        App-->>Browser: 渲染 orders.html（含分页数据）

        Note over User, DB: 查看详情
        User->>Browser: 点击「查看详情」
        Browser->>App: GET /api/orders/<order_id>
        App->>DB: SELECT * FROM orders WHERE order_id=?
        DB-->>App: order row
        App-->>Browser: {order: {...}}
        Browser->>Browser: 弹出详情模态框

        Note over User, DB: 重新下载
        User->>Browser: 点击「下载」
        Browser->>App: GET /api/download/<order_id>?format=...
        App->>App: 根据 original_format 生成文件
        App-->>Browser: 文件下载

        Note over User, DB: 重新改写（7天内免费）
        User->>Browser: 点击「再次改写」
        Browser->>App: POST /api/orders/<order_id>/rehumanize
        App->>DB: 检查 expires_at > now
        App->>App: humanizer.humanize(original_text)
        App->>DB: Order.update_rewrite(...)
        App-->>Browser: {success, rewritten}
        Browser->>Browser: 跳转到首页展示结果
    end
```

### 6.5 支付状态机

```mermaid
stateDiagram-v2
    [*] --> pending: 创建订单
    pending --> paid: 支付成功\n(webhook/confirm)
    pending --> expired: 超时 30 分钟
    paid --> processing: 启动后台改写
    processing --> completed: 改写完成
    processing --> expired: 改写超时
    completed --> [*]
    expired --> [*]

    note right of pending
        等待用户支付
        前端每 3s 轮询
    end note

    note right of paid
        支付已确认
        改写线程启动中
    end note

    note right of processing
        后台线程执行:
        1. humanize(text)
        2. analyze_text(result)
        3. update_result()
    end note

    note right of completed
        改写结果已保存
        前端展示对比结果
    end note
```

### 6.6 交互流程决策

```mermaid
flowchart TD
    A[用户检测完成<br>看到完整结果] --> B{用户点击改写?}
    B -->|未点击| C[继续浏览结果<br>或关闭页面]
    
    B -->|点击改写| D{已登录?}
    D -->|否| E[弹出登录/注册]
    E -->|登录成功| F{价格?}
    D -->|是| F
    
    F -->|免费| G[POST /api/rewrite]
    G -->|同步改写| H[展示对比结果]
    
    F -->|付费| I[POST /api/create-payment]
    I --> J[创建 pending 订单<br>生成 QR 码]
    J --> K[前端渲染 QR + 3s 轮询]
    K --> L[用户扫码支付]
    L --> M[Webhook 异步通知]
    M --> N[标记 paid + 启动后台线程]
    N --> O[异步改写完成]
    O --> P[轮询检测到 completed]
    P --> H
```

---

## 7. 检测引擎

### 7.1 五维加权评分模型

```mermaid
mindmap
    root((AI 检测引擎<br>五维加权))
        Readability<br>69.5%
            FOG Index
            句式复杂度
            词汇多样性
        Perplexity<br>17.2%
            文本困惑度
            语言模型评分
        Pattern<br>13.4%
            AI 典型模式
            重复句式检测
            过渡词密度
        输出
            ai_score 百分比
            逐段评分
            高亮标红 >50%
```

### 7.2 检测流程

```mermaid
flowchart TD
    A[输入文本] --> B[分段处理]
    B --> C[Readability 分析\n69.5% 权重]
    B --> D[Perplexity 计算\n17.2% 权重]
    B --> E[Pattern 匹配\n13.4% 权重]
    C --> F[加权合成]
    D --> F
    E --> F
    F --> G[段落级 AI Score]
    G --> H[整文综合 AI Score]
    H --> I[返回结果\nai_score + 逐段评分]
```

---

## 8. 改写引擎

### 8.1 6 种变换策略

```mermaid
flowchart LR
    A[原始文本] --> B[基于 MD5 种子的<br>确定性算法]

    B --> C1[同义词替换]
    B --> C2[句式重组]
    B --> C3[主动/被动转换]
    B --> C4[连接词变换]
    B --> C5[段落重排]
    B --> C6[词汇升级]

    C1 --> D[改写结果]
    C2 --> D
    C3 --> D
    C4 --> D
    C5 --> D
    C6 --> D

    D --> E[保持原意不变]
    E --> F[AI 率降低 30-50pp]
```

### 8.2 改写模式

| 模式 | 策略 | 效果 |
|------|------|------|
| `academic`（默认） | 全部 6 种策略均衡应用 | 学术文风保持 |
| `conservative` | 保守策略子集 | 最小改动，安全改写 |
| `deep` | 全部策略 + 深度重组 | 最大程度降 AI 率 |

---

## 9. 文件结构

### 9.1 项目目录

```mermaid
mindmap
    root((AI Humanizer))
        核心文件
            app.py<br>Flask 主应用+路由
            ai_checker.py<br>AI 检测引擎
            humanize.py<br>规则改写引擎
            models.py<br>数据模型 User/Order
        适配器
            payment_adapter.py<br>支付适配器
            humanizer_adapter.py<br>改写适配器
        前端
            templates/
                index.html<br>主页
                orders.html<br>订单页
            static/
                script.js<br>交互逻辑
                style.css<br>样式
        数据
            instance/<br>SQLite 数据库
            uploads/<br>临时文件
        配置
            requirements.txt
            .env.example
```

### 9.2 变更清单

#### 新增文件

| 文件 | 说明 |
|------|------|
| `models.py` | SQLite 数据模型 + `init_db()` + 支付方法 |
| `payment_adapter.py` | 支付适配器 (Mock + Alipay) |
| `humanizer_adapter.py` | 改写适配器 (RuleBased + Api 占位) |
| `templates/orders.html` | 订单历史页面 |

#### 修改文件

| 文件 | 变更内容 |
|------|----------|
| `app.py` | DB 初始化、auth 路由、QR 码支付、Webhook、异步改写、下载 API |
| `templates/index.html` | 导航栏改造、登录/注册模态框、FAQ 更新 |
| `static/script.js` | 登录/注册、QR 支付渲染、轮询、订单交互 |
| `static/style.css` | 模态框、QR 码区域、订单详情样式 |
| `requirements.txt` | 新增 alipay-sdk-python，版本号范围约束 |

#### 不变文件

| 文件 | 理由 |
|------|------|
| `ai_checker.py` | 检测逻辑无需修改 |
| `humanize.py` | 通过 adapter 包装调用 |

---

## 10. 共享约定

| 约定 | 值 |
|------|-----|
| **Session Key** | `session['user_id']` 存用户 ID；`session['last_text']` 服务端兜底；`sessionStorage.lastExtractedText` **前端主存**（避免 session 丢失导致文本不可用） |
| **订单号格式** | `ORD-` + uuid4 hex[:8].upper()，例 `ORD-A1B2C3D4` |
| **数据库路径** | `instance/aigc_humanizer.db` |
| **时间格式** | ISO 8601 UTC (`datetime.utcnow().isoformat()`) |
| **API 响应** | 成功: `{success: true, ...}`；失败: `{error: "消息"}` |
| **价格** | `PRICE_PER_1000_WORDS = 14.9`, `FREE_WORD_LIMIT = 200`, `FREE_DAILY_REWRITES = 2` |
| **密码安全** | `werkzeug.security.generate_password_hash` (pbkdf2:sha256) |
| **订单过期** | `expires_at = created_at + 7 days`；未支付 30 分钟过期 |
| **适配器配置** | `PAYMENT_ADAPTER=mock/alipay`, `HUMANIZER_ADAPTER=rule_based/api` |
| **QR 码有效期** | 预支付订单 30 分钟 |
| **轮询间隔** | 前端每 3 秒，最多 200 次（10 分钟） |
| **后台改写** | `threading.Thread(daemon=True)` |

---

## 11. 任务列表

| # | 任务 | 涉及文件 | 状态 |
|---|------|----------|------|
| T01 | 基础设施 + 数据层（DB 模型 + 支付适配器 + 改写适配器） | `models.py`, `payment_adapter.py`, `humanizer_adapter.py`, `app.py` | ✅ 已完成 |
| T02 | 后端认证系统 + 订单持久化路由 | `app.py`, `models.py` | ✅ 已完成 |
| T03 | 格式保持输出 + .md 支持 + 下载 API | `app.py`, `templates/index.html`, `static/script.js` | ✅ 已完成 |
| T04 | 前端登录/注册模态框 + 导航栏改造 | `templates/index.html`, `static/style.css`, `static/script.js` | ✅ 已完成 |
| T05 | 订单历史页面 | `templates/orders.html`, `static/style.css`, `static/script.js` | ✅ 已完成 |
| T06 | QR 码支付流程（支付宝当面付） | `app.py`, `payment_adapter.py`, `models.py`, `static/script.js` | ✅ 已完成 |
| T07 | 支付宝 Webhook + 异步后台改写 | `app.py`, `models.py` | ✅ 已完成 |

---

*文档整合于 2026-05-28。原始来源：ARCHITECTURE.md、product-doc.md（第3章技术架构）、class-diagram.mermaid、sequence-diagram.mermaid*
