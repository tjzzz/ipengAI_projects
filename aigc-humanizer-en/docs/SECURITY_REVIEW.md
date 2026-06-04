# 安全分析与支付防绕过方案

> **版本**: v1.0 | **日期**: 2026-05-28
> **审阅范围**: 代码逻辑、支付流程、数据安全、防绕过

---

## 1. 风险总览

| 风险等级 | 数量 | 说明 |
|----------|------|------|
| 🔴 严重 | 3 | 直接导致免费改写或服务不可用 |
| 🟡 中危 | 4 | 数据泄露或可被利用但不直接造成经济损失 |
| 🟢 低危 | 3 | 配置不合理或缺少防御纵深 |

---

## 2. 严重风险

### S-01: Mock 支付模式下无验证 (CRITICAL)

**描述**: 默认 `PAYMENT_ADAPTER=mock`，`MockPaymentAdapter.verify_payment()` 仅校验 `token.startswith("PAY-")`。攻击者登录后即可构造任意 PAY- 前缀 token 调用 `/api/confirm-payment` 免费改写。

**攻击路径**:
1. 注册账号 → 登录
2. `POST /api/rewrite {text, mode}` → 获得 session pending_rewrite
3. 伪造 `payment_token = "PAY-fake"`
4. `POST /api/confirm-payment {payment_token}` → 获得改写结果
5. 可无限循环

**修复方案**:
- 生产环境严禁使用 MockPaymentAdapter
- `app.py` 启动时增加环境检查：如果 `PAYMENT_ADAPTER=mock` 且 `FLASK_ENV=production`，拒绝启动
- 旧版 `/api/rewrite` + `/api/confirm-payment` 流程在非 mock 模式下应完全禁用

### S-02: Mock Webhook 可被伪造 (CRITICAL)

**描述**: `MockPaymentAdapter.verify_notification()` 不验证签名，仅检查 `trade_status=TRADE_SUCCESS`。攻击者 POST 任意请求到 `/api/webhook/alipay` 即可触发支付成功。

**攻击路径**:
1. 创建正常支付订单，获得 `order_id`
2. POST `/api/webhook/alipay` 带上 `out_trade_no={order_id}&trade_status=TRADE_SUCCESS`
3. Webhook 返回 `"success"`，订单被标记为已支付 → 后台改写 → 免费获取结果

**修复方案**:
- Mock 模式下禁用生产环境部署（同 S-01）
- Webhook 端点应增加 IP 白名单（仅允许支付宝网关 IP）
- 增加通知重放防护（`trade_no` 唯一性检查）

### S-03: 后台线程访问 Flask session 导致崩溃 (CRITICAL)

**描述**: `_process_payment_success()` 在后台线程中访问 `session[f'order_{order_id}_mode']`。Flask session 是请求上下文绑定的线程局部对象，后台线程中访问会抛出 `RuntimeError`。

**影响**:
- Webhook 流程在验签通过后，后台线程直接崩溃
- 订单永远停留在 `processing` 状态
- 用户支付后永远拿不到改写结果

**根因**: `mode` 存入 session 而非 DB。订单的 `mode` 已在 `create_payment_record()` 时存入 DB，但后台线程仍试图从 session 读取。

**修复方案**:
- 后台线程直接读 `order['mode']` 从 DB 获取，无需 session

---

## 3. 中危风险

### M-01: `get_db()` 连接管理不当

**文件**: [app.py:39-44](app.py#L39)

**描述**: 数据库连接存储在 `app.config` 而非 Flask `g` 对象。`app.config` 是应用级全局变量，多线程/多 worker 下不同请求会互相覆盖连接。

**影响**: 部署在 gunicorn/uWSGI 多 worker 模式下可能产生数据库连接串话。

**修复方案**: 使用 `flask.g` 存储请求级连接，或改用 Flask-SQLAlchemy。

### M-02: 旧版支付流程无金额校验

**文件**: [app.py:544-551](app.py#L544)

**描述**: `/api/confirm-payment` 仅校验 payment_token，不校验金额。结合 Mock 模式漏洞，攻击者可以任意金额改写。

**修复方案**: 旧版流程也应验证 `pending.price` 与订单价格一致。

### M-03: 无 CSRF 保护 + 无 Rate Limiting

**描述**: 所有 API 端点缺少 CSRF token 和请求频率限制。

**影响**:
- 攻击者可利用 CSRF 让用户执行非自愿操作（logout、register）
- 高频调用 `/api/analyze` 消耗服务器资源
- `threading.Thread` 每调用一次 rewrite 就启动一个线程，无限制下可导致线程资源耗尽

**修复方案**:
- 关键端点（支付、改写）增加 CSRF token
- 增加 `flask-limiter` 进行频次控制
- 限制最大并发后台线程数

### M-04: 后台线程失败无恢复机制

**文件**: [app.py:872-897](app.py#L872)

**描述**: 如果后台改写线程失败（analyze_text 抛异常或其他错误），订单永久卡在 `processing`。没有重试机制、超时机制、或手动恢复端点。

**修复方案**:
- 增加重试逻辑（最多 3 次）
- 增加失败后恢复管理端点（admin）
- 记录详细失败原因到订单扩展字段

---

## 4. 低危风险

### L-01: 默认 SECRET_KEY

**文件**: [app.py:23](app.py#L23)

默认 `SECRET_KEY` 为硬编码字符串。生产环境必须通过环境变量设置。已在文档和 `.env.example` 中说明。

### L-02: SQLite 并发写入冲突

**描述**: `threading.Thread` 后台改写完成后写入 DB，与主线程的读取可能冲突。SQLite 的 WAL 模式缓解了读写冲突，但高频写入（多订单同时处理）可能产生 `database is locked` 错误。

**修复方案**: 增加写冲突重试逻辑，或切换到 PostgreSQL 等并发友好的数据库。

### L-03: PDF 排版粗糙

**文件**: [app.py:114-132](app.py#L114)

生成的 PDF 仅是纯文本简单写入，无分页、字体选择粗糙。用户下载后可能不满意格式。

---

## 5. 整体防护方案

### 5.1 支付状态机

详见 [TECHNICAL_ARCHITECTURE.md §6.5 支付状态机](TECHNICAL_ARCHITECTURE.md#65-支付状态机)，此处不复述。

关键安全约束：
- `pending → paid`：必须通过签名验证 + 金额匹配 + 订单状态检查（三重校验）
- `pending → expired`：30 分钟超时自动过期，防止订单悬挂
- `processing → completed`：后台线程成功后唯一出口，失败应进入 `expired`（待修复，见 M-04）

### 5.2 支付验证链

每笔支付必须通过以下全部检查才算有效：

1. **签名验证** (Alipay): RSA2 签名验证，确保通知来自支付宝
2. **金额匹配**: 通知金额与订单金额完全一致（±0.01）
3. **订单状态**: 订单为 `pending`，防重复通知
4. **应用验证**: `app_id` 与配置一致

### 5.3 部署检查清单

| 检查项 | 必/选 | 说明 |
|--------|-------|------|
| 设置 `SECRET_KEY` 环境变量 | 必 | 使用 `secrets.token_hex(32)` 生成 |
| 设置 `PAYMENT_ADAPTER=alipay` | 必 | 生产环境禁止使用 mock |
| 配置支付宝密钥和证书 | 必 | 当面付 APP_ID + RSA2 密钥 |
| `ALIPAY_NOTIFY_URL` 可公网访问 | 必 | 支付宝回调必须可达 |
| HTTPS 证书 | 必 | 防止中间人攻击 |
| Nginx 反向代理 + 限流 | 推 | `limit_req` 控制 `/api/analyze` 频率 |
| 禁用 `/api/test/mock-payment` | 必 | 生产环境删除或加 IP 白名单 |
| 数据库定期备份 | 推 | 订单数据不可丢失 |
| 后台线程池上限 | 推 | 限制最大并发改写数 |
| 监控 alert（异常订单激增） | 选 | 防刷单检测 |
| 禁用旧版 `/api/rewrite` 流程 | 选 | Mock 模式特有的漏洞，建议仅保留 QR 码流程 |

### 5.4 监控与告警

建议监控以下指标：

- **同一 IP 每分钟创建订单数**：超过阈值触发风控
- **同一账号每日订单数**：异常刷单检测
- **卡在 processing 超过 5 分钟的订单**：后台线程异常告警
- **webhook 签名失败次数**：可能是攻击尝试
- **amount 不匹配的 webhook**：金额篡改攻击

---
## 6. 已修复问题清单

| # | 问题 | 严重程度 | 修复方式 |
|---|------|----------|----------|
| S-03 | 后台线程 session 崩溃 | 🔴 严重 | 改为从 DB 读取 `order['mode']` |
| L-01 | 前端模式选择缺失 | 🟡 中 | QR 支付流程增加 mode 参数传递 |

---

*文档结束*
