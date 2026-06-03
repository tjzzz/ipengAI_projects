# 用户流程可视化

```mermaid
flowchart TD
    H[首页 /] -->|上传文件 / 粘贴文本| AC[点击「立即检测 AI 率」]
    
    AC -->|POST /api/analyze| AN[执行 AI 检测]
    AN -->|返回分析结果| L1{已登录?}
    
    L1 -->|否| LR{价格 > 0?}
    LR -->|免费 <=500词| S1[标记 pendingFreeRewrite]
    LR -->|付费 >500词| S2[标记 pendingPaidAnalysis + 存储价格/字数]
    S1 & S2 --> LA[弹出登录/注册弹窗]
    
    LA -->|用户登录| LN[调用 /api/login]
    LN -->|成功| PL{有 pending 标记?}
    
    PL -->|pendingFreeRewrite| FRW[执行免费改写]
    PL -->|pendingPaidAnalysis| PM[弹出支付弹窗]
    
    LA -->|用户注册| RG[调用 /api/register]  
    RG -->|成功| PL
    
    LA -->|关闭弹窗| ED[结束 — 无操作]
    
    L1 -->|是| PZ{价格?}
    
    PZ -->|免费 price === 0| FRW
    PZ -->|付费 price > 0| PM
    
    PM -->|点击「确认支付」| CP[POST /api/create-payment]
    CP -->|返回 QR 码| QR[显示支付二维码]
    QR -->|Mock 模式| MP[点击「模拟支付成功」]
    QR -->|支付宝模式| SP[用户扫码支付]
    
    MP & SP --> PP[POST /api/payment-status 轮询]
    PP -->|每 3 秒| PS{支付状态?}
    
    PS -->|pending| PP
    PS -->|paid → 后台改写中| BG[后台线程执行改写]
    BG -->|改写完成 status=completed| DR[显示改写结果 + 对比]
    
    PS -->|completed| DR
    
    DR -->|点击「复制结果」| CPY[复制到剪贴板]
    DR -->|点击「下载」| DL[选择格式下载]
    
    subgraph 订单管理
        O[导航到 /orders] -->|GET /api/orders| OL[展示订单列表]
        OL -->|点击订单| OD[GET /api/orders/:id 展示详情]
        OD -->|点击「重新改写」| RH[POST /api/orders/:id/rehumanize]
        RH -->|免费 ≤500词| FRW2[重新执行改写]
        RH -->|付费 >500词| PM2[重新走支付流程]
        OD -->|点击「下载」| DL2[选择格式下载]
    end
    
    subgraph 登录/注册弹窗
        LOG[登录 Tab] -->|提交| LN
        REG[注册 Tab] -->|提交| RG
    end
    
    subgraph 辅助接口
        CONF[GET /api/payment-config → 前端获取支付模式]
        PREV[POST /api/preview-rewrite → 免费预览改写]
        SUGG[POST /api/suggestion-detail → 段落级修改建议]
    end

    subgraph 下载逻辑
        DLF["GET /api/download/:id?format=docx|pdf|txt|md"]
        DLF -->|登录用户| C1{订单属于当前用户?}
        DLF -->|未登录| C2{会话中有 last_rewritten?}
        C1 -->|是| GEN[生成文件并返回]
        C1 -->|否| ERR1[403 无权访问]
        C2 -->|是| GEN
        C2 -->|否| ERR2[401 请登录]
    end
```

## 关键路径速览

### 路径 A：免费改写（≤500 词，未登录）
```
首页 → 检测 → 弹出登录 → 登录/注册 → 自动执行改写 → 显示结果
```

### 路径 B：免费改写（≤500 词，已登录）
```
首页 → 检测 → 立即执行改写 → 显示结果
```

### 路径 C：付费改写（>500 词，未登录）
```
首页 → 检测 → 弹出登录 → 登录/注册 → 弹出支付弹窗 → 扫码支付 → 轮询 → 显示结果
```

### 路径 D：付费改写（>500 词，已登录）
```
首页 → 检测 → 弹出支付弹窗 → 扫码支付 → 轮询 → 显示结果
```

## 后端关键路由表

| 路由 | 需登录 | 功能 | 触发时机 |
|------|--------|------|---------|
| `POST /api/analyze` | 否 | AI 检测 | 点击「立即检测」 |
| `POST /api/rewrite` | 是 | 免费改写 | 分析结果 → 免费 |
| `POST /api/create-payment` | 是 | 创建支付订单 | 点击「确认支付」 |
| `GET /api/payment-status/:id` | 是 | 轮询支付+改写状态 | 支付后 3 秒/次 |
| `POST /api/webhook/alipay` | 否(CSRF豁免) | 支付宝回调 | 支付宝异步通知 |
| `POST /api/test/mock-payment/:id` | 否 | 模拟支付成功 | Mock 模式测试 |
| `GET /api/orders` | 是 | 订单列表 | 导航到 /orders |
| `POST /api/orders/:id/rehumanize` | 是 | 重新改写 | 点击「重新改写」 |
| `GET /api/download/:id` | 视情况 | 下载结果 | 点击「下载」 |
| `GET /api/payment-config` | 否 | 获取支付适配器类型 | 页面加载 |

## Session 标记位

| 标记 | 设置位置 | 消费位置 | 用途 |
|------|---------|---------|------|
| `pendingFreeRewrite` | `handleAnalyzeResponse` | `auth.js` 登录/注册成功 | 登录后自动执行免费改写 |
| `pendingPaidAnalysis` | `handleAnalyzeResponse` / `createPaymentOrder` | `auth.js` 登录/注册成功 | 登录后自动弹出支付弹窗 |
| `pendingPaymentInfo` | `handleAnalyzeResponse` | `auth.js` 登录/注册成功 | 存储支付需要的字数/价格 |
| `last_text` | `api_analyze` | `api_rewrite` / `api_create-payment` | 改写和支付时读取文本 |