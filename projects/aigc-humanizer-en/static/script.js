/* ========== CSRF HELPER ========== */
function _csrfFetch(url, options) {
    /* Attach X-CSRFToken header to POST/PUT/DELETE requests */
    if (['POST', 'PUT', 'DELETE'].includes((options?.method || '').toUpperCase())) {
        const token = document.querySelector('meta[name="csrf-token"]')?.content;
        if (token) {
            options = { ...options, headers: { ...options?.headers, 'X-CSRFToken': token } };
        }
    }
    return fetch(url, options);
}

/* ========== EXTRACTED TEXT (P0-2: on-demand fetch) ========== */
function _fetchExtractedText() {
    _csrfFetch('/api/extracted-text', { method: 'GET' })
        .then(res => res.ok ? res.json() : null)
        .then(data => { if (data?.text) sessionStorage.setItem('lastExtractedText', data.text); })
        .catch(() => {});
}

/* ========== DOM REFS ========== */
/* Note: These may be null on pages like /orders — guard with null checks */
const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const textInput = document.getElementById('text-input');
const analyzeBtn = document.getElementById('analyze-btn');
const uploadForm = document.getElementById('upload-form');

/* ========== FILE UPLOAD ========== */
let uploadedFile = null;

// Store latest result info for download
let latestResult = null;

// Click to upload (only on main page)
if (dropZone && fileInput) {
    dropZone.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (file) handleFileSelect(file);
    });

    // Drag & drop
    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropZone.classList.add('dragover');
    });
    dropZone.addEventListener('dragleave', () => {
        dropZone.classList.remove('dragover');
    });
    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('dragover');
        const file = e.dataTransfer.files[0];
        if (file) handleFileSelect(file);
    });
}

function handleFileSelect(file) {
    const ext = file.name.split('.').pop().toLowerCase();
    if (!['docx', 'pdf', 'txt', 'md'].includes(ext)) {
        showToast('仅支持 .docx、.pdf、.txt、.md 格式', 'error');
        return;
    }
    if (file.size > 20 * 1024 * 1024) {
        showToast('文件大小不能超过 20MB', 'error');
        return;
    }
    uploadedFile = file;
    if (dropZone) {
        dropZone.classList.add('has-file');
        const dropTextEl = dropZone.querySelector('.drop-text');
        if (dropTextEl) dropTextEl.textContent = `📄 ${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
    }
    if (textInput) textInput.value = '';
    showToast(`已选择文件：${file.name}`, 'success');
}

/* ========== ANALYZE ========== */
if (uploadForm) {
    uploadForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        await analyzeText();
    });
}

async function analyzeText() {
    showLoading();

    try {
        // File takes priority
        if (uploadedFile) {
            const formData = new FormData();
            formData.append('file', uploadedFile);
            const resp = await _csrfFetch('/api/analyze', { method: 'POST', body: formData });
            const data = await resp.json();
            handleAnalyzeResponse(data);
        } else {
            const text = textInput.value.trim();
            if (!text) {
                hideLoading();
                showToast('请上传文档或粘贴英文文本', 'error');
                return;
            }
            const wordCount = text.split(/\s+/).filter(Boolean).length;
            if (wordCount < 10) {
                hideLoading();
                showToast('文本太短，请提供至少 50 个字符', 'error');
                return;
            }
            const resp = await _csrfFetch('/api/analyze', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text })
            });
            const data = await resp.json();
            handleAnalyzeResponse(data);
        }
    } catch (err) {
        hideLoading();
        showToast(getNetworkErrorMessage(err), 'error');
        console.error('分析出错:', err);
    }
}

function handleAnalyzeResponse(data) {
    hideLoading();
    if (data.error) {
        if (data.over_limit) {
            showOverLimitUpgrade(data);
            return;
        }
        showToast(data.error, 'error');
        return;
    }

    const analysis = data.analysis;
    displayResults(analysis, data.word_count, data.price);

    // Store format info for later download
    if (data.original_format) {
        sessionStorage.setItem('lastOriginalFormat', data.original_format);
        sessionStorage.setItem('lastOriginalFilename', data.original_filename || 'humanized');
    } else {
        sessionStorage.setItem('lastOriginalFormat', 'txt');
        sessionStorage.setItem('lastOriginalFilename', 'humanized');
    }

    scrollToResults();

    // If uploaded via file, fetch extracted text on-demand for later rewrite use
    if (data.has_extracted_text) {
        _fetchExtractedText();
    }
}

/* ========== OVER LIMIT UPGRADE ========== */
function showOverLimitUpgrade(data) {
    const section = document.getElementById('result-section');
    section.style.display = 'block';

    // Fetch extracted text on-demand so paid flow can use it
    if (data.has_extracted_text) {
        _fetchExtractedText();
    }

    const wordCount = data.word_count;
    const price = data.price || (wordCount / 1000 * 14.9).toFixed(2);

    // Clear sub-sections (they're empty in over-limit case, but be safe)
    document.getElementById('sub-scores').innerHTML = '';
    document.getElementById('suggestions-list').innerHTML = '';
    document.getElementById('paragraph-list').innerHTML = '';
    document.querySelector('.result-actions').style.display = 'none';

    scrollToResults();

    // Store payment info for post-login flow
    sessionStorage.setItem('pendingPaymentInfo', JSON.stringify({
        wordCount, price, mode: 'academic'
    }));

    // Check login first — don't show payment modal if not logged in
    // Wait for login status check to complete
    (async () => {
        if (loginStatusPromise) {
            await loginStatusPromise;
        }

        if (!currentUser) {
            sessionStorage.setItem('pendingPaidAnalysis', 'true');
            showAuthModal('login');
            showToast('请先登录，登录后将自动创建订单', 'info');
            return;
        }

        // User is logged in, show payment modal directly
        showPaymentModal();
        document.getElementById('pay-word-count').textContent = wordCount + ' 词';
        document.getElementById('pay-price').textContent = '¥' + price;
        document.getElementById('pay-btn-price').textContent = price;
        document.getElementById('pay-btn').disabled = true;
        document.getElementById('pay-btn').innerHTML = '⏳ 正在生成支付订单...';
        document.getElementById('payment-qr-section').style.display = 'none';

        createPaymentOrder(wordCount, price, 'academic');
    })();
}

async function createPaymentOrder(wordCount, price, mode = 'academic') {
    // Check login first
    if (!currentUser) {
        sessionStorage.setItem('pendingPaidAnalysis', 'true');
        showAuthModal('login');
        showToast('请先登录，登录后将自动创建订单', 'info');
        return;
    }

    const text = getCurrentText();
    if (!text) {
        showToast('没有可分析的文本，请重新上传', 'error');
        closePaymentModal();
        return;
    }

    try {
        const resp = await _csrfFetch('/api/create-payment', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text, mode: mode || 'academic' })
        });
        const data = await resp.json();

        if (data.error) {
            if (data.login_required) {
                sessionStorage.setItem('pendingPaidAnalysis', 'true');
                closePaymentModal();
                showAuthModal('login');
                return;
            }
            showToast(data.error, 'error');
            closePaymentModal();
            return;
        }

        // Render payment UI with QR code in modal
        renderPaymentQR(data.order, wordCount, price);

        // Start polling for payment status
        startPaymentPolling(data.order.order_id);

    } catch (err) {
        showToast(getNetworkErrorMessage(err), 'error');
        console.error('创建订单失败:', err);
        closePaymentModal();
    }
}

function renderPaymentQR(order, wordCount, price) {
    const qrCode = order.qr_code;

    // Update payment modal content instead of destroying score-card
    document.getElementById('pay-word-count').textContent = wordCount + ' 词';
    document.getElementById('pay-price').textContent = '¥' + parseFloat(price).toFixed(2);
    document.getElementById('qr-pay-price').textContent = '¥' + parseFloat(price).toFixed(2);

    // Hide default payment button and show QR section in modal
    document.getElementById('pay-btn').style.display = 'none';
    const qrSection = document.getElementById('payment-qr-section');
    qrSection.style.display = 'block';

    // Reset poll status
    document.getElementById('poll-status').innerHTML = '⏳ 等待支付中...';
    document.getElementById('poll-timer').textContent = '';

    // Mock payment button handler (re-attach each time to avoid duplicates)
    const mockBtn = document.getElementById('mock-pay-btn');
    if (mockBtn) {
        // Remove old listeners by cloning
        const newMockBtn = mockBtn.cloneNode(true);
        mockBtn.parentNode.replaceChild(newMockBtn, mockBtn);
        newMockBtn.addEventListener('click', async () => {
            newMockBtn.disabled = true;
            newMockBtn.textContent = '处理中...';
            try {
                const resp = await _csrfFetch(`/api/test/mock-payment/${order.order_id}`, { method: 'POST' });
                const data = await resp.json();
                if (data.success) {
                    showToast('支付模拟成功！', 'success');
                    document.getElementById('poll-status').innerHTML = '✅ 支付成功，正在改写...';
                } else {
                    showToast(data.error || '模拟失败', 'error');
                    newMockBtn.disabled = false;
                    newMockBtn.textContent = '🧪 模拟支付成功（测试用）';
                }
            } catch (err) {
                showToast('请求失败', 'error');
                newMockBtn.disabled = false;
                newMockBtn.textContent = '🧪 模拟支付成功（测试用）';
            }
        });
    }

    // Render QR code using qrcode.js
    const container = document.getElementById('qrcode-container');
    if (container) {
        container.innerHTML = '';
        if (qrCode && typeof QRCode !== 'undefined') {
            new QRCode(container, {
                text: qrCode,
                width: 150,
                height: 150,
                colorDark: "#000000",
                colorLight: "#ffffff",
                correctLevel: QRCode.CorrectLevel.M
            });
        } else if (qrCode) {
            // Fallback if qrcode.js not loaded - show QR string as link
            container.innerHTML = `<a href="${qrCode}" target="_blank" style="color:var(--primary);font-size:0.85rem;">点击打开支付宝付款</a>`;
        }
    }
}

let pollInterval = null;
let pollCount = 0;
const MAX_POLL_COUNT = 200; // 10 minutes at 3-second intervals

function startPaymentPolling(orderId) {
    // Clear any existing polling
    if (pollInterval) {
        clearInterval(pollInterval);
    }
    pollCount = 0;

    pollInterval = setInterval(async () => {
        pollCount++;
        if (pollCount > MAX_POLL_COUNT) {
            clearInterval(pollInterval);
            document.getElementById('poll-status').innerHTML = '⏰ 订单已超时，请重新检测';
            return;
        }

        // Update timer display (mm:ss format)
        const remainingSecs = (MAX_POLL_COUNT - pollCount) * 3;
        const mm = String(Math.floor(remainingSecs / 60)).padStart(2, '0');
        const ss = String(remainingSecs % 60).padStart(2, '0');
        document.getElementById('poll-timer').textContent = `${mm}:${ss}`;

        try {
            const resp = await fetch(`/api/payment-status/${orderId}`);
            const data = await resp.json();

            if (data.payment_status === 'paid' || data.status === 'processing') {
                document.getElementById('poll-status').innerHTML = '✅ 支付成功，正在改写...';
            }

            if (data.status === 'completed' && data.rewritten) {
                clearInterval(pollInterval);
                closePaymentModal();
                // Show rewrite result
                displayRewriteResult(data);
                showToast('改写完成！', 'success');
            }
        } catch (err) {
            // Silently continue polling on error
        }
    }, 3000);
}

// Legacy functions kept for backward compatibility but not used in new flow
async function startPaidAnalysis() {
    if (!currentUser) {
        sessionStorage.setItem('pendingPaidAnalysis', 'true');
        showAuthModal('login');
        showToast('请先登录，登录后将自动跳转到付费检测', 'info');
        return;
    }
    createPaymentOrder();
}

// Listen for login completion to resume paid analysis
document.addEventListener('DOMContentLoaded', () => {
    // Original rehumanize result check
    const resultStr = sessionStorage.getItem('rehumanizeResult');
    if (resultStr) {
        try {
            const data = JSON.parse(resultStr);
            sessionStorage.removeItem('rehumanizeResult');
            setTimeout(() => displayRewriteResult(data), 500);
        } catch (e) { /* ignore */ }
    }

    // Pending paid analysis after login - auto create payment order
    const pendingPaid = sessionStorage.getItem('pendingPaidAnalysis');
    if (pendingPaid) {
        sessionStorage.removeItem('pendingPaidAnalysis');
        const pendingInfo = JSON.parse(sessionStorage.getItem('pendingPaymentInfo') || '{}');
        sessionStorage.removeItem('pendingPaymentInfo');
        const wc = pendingInfo.wordCount || 0;
        const pr = pendingInfo.price || 0;
        setTimeout(() => {
            showPaymentModal();
            document.getElementById('pay-word-count').textContent = wc + ' 词';
            document.getElementById('pay-price').textContent = '¥' + pr;
            document.getElementById('pay-btn-price').textContent = pr;
            document.getElementById('pay-btn').disabled = true;
            document.getElementById('pay-btn').innerHTML = '⏳ 正在生成支付订单...';
            document.getElementById('payment-qr-section').style.display = 'none';
            createPaymentOrder(wc, pr, pendingInfo.mode || 'academic');
        }, 800);
    }
});

/* ========== DISPLAY RESULTS ========== */
function displayResults(analysis, wordCount, price) {
    const section = document.getElementById('result-section');
    section.style.display = 'block';

    // Score ring
    const score = analysis.overall.ai_score;
    const circumference = 339.292;
    const offset = circumference - (score / 100) * circumference;
    const scoreFill = document.getElementById('score-fill');
    scoreFill.style.strokeDashoffset = offset;

    // Color based on score
    if (score < 20) {
        scoreFill.style.stroke = '#10b981';
        document.getElementById('risk-level').textContent = '✅ 安全';
        document.getElementById('risk-level').style.color = '#065f46';
    } else if (score < 40) {
        scoreFill.style.stroke = '#f59e0b';
        document.getElementById('risk-level').textContent = '⚠️ 需关注';
        document.getElementById('risk-level').style.color = '#92400e';
    } else if (score < 60) {
        scoreFill.style.stroke = '#f97316';
        document.getElementById('risk-level').textContent = '🔶 中等风险';
        document.getElementById('risk-level').style.color = '#9a3412';
    } else {
        scoreFill.style.stroke = '#ef4444';
        document.getElementById('risk-level').textContent = '🔴 高风险';
        document.getElementById('risk-level').style.color = '#991b1b';
    }

    document.getElementById('ai-score-value').textContent = score;
    document.getElementById('risk-desc').textContent = analysis.overall.risk_description;

    // Animate score
    animateCounter('ai-score-value', 0, score, 1000);

    // Sub-scores
    const subScores = analysis.overall.sub_scores;
    const subContainer = document.getElementById('sub-scores');
    subContainer.innerHTML = '';

    const scoreLabels = {
        perplexity_score: '困惑度',
        burstiness_score: '突发性',
        pattern_score: 'AI 模式',
        readability_score: '可读性',
        structure_score: '结构'
    };

    Object.entries(subScores).forEach(([key, value]) => {
        const label = scoreLabels[key] || key;
        const color = value > 60 ? '#ef4444' : value > 30 ? '#f59e0b' : '#10b981';

        subContainer.innerHTML += `
            <div class="sub-score-item">
                <div class="sub-score-label">${label}</div>
                <div class="sub-score-value" style="color:${color}">${value}</div>
                <div class="sub-score-bar">
                    <div class="sub-score-fill" style="width:0%;background:${color}" data-target="${value}"></div>
                </div>
            </div>
        `;
    });

    // Animate sub-score bars after a short delay
    setTimeout(() => {
        document.querySelectorAll('.sub-score-fill').forEach(el => {
            el.style.width = el.dataset.target + '%';
        });
    }, 200);

    // Suggestions
    const suggestionsList = document.getElementById('suggestions-list');
    suggestionsList.innerHTML = '';

    if (analysis.suggestions && analysis.suggestions.length > 0) {
        analysis.suggestions.forEach(s => {
            suggestionsList.innerHTML += `
                <div class="suggestion-item severity-${s.severity}">
                    <div class="suggestion-icon">${s.icon}</div>
                    <div class="suggestion-content">
                        <div class="suggestion-title">${s.title}</div>
                        <div class="suggestion-detail">${s.detail}</div>
                    </div>
                </div>
            `;
        });
    }

    // Paragraph analysis
    const paragraphList = document.getElementById('paragraph-list');
    paragraphList.innerHTML = '';

    if (analysis.paragraphs && analysis.paragraphs.length > 0) {
        analysis.paragraphs.forEach(p => {
            const pScore = p.ai_score;
            let riskClass = 'risk-safe', riskText = '安全';
            if (pScore >= 40) { riskClass = 'risk-high'; riskText = '高风险'; }
            else if (pScore >= 20) { riskClass = 'risk-warning'; riskText = '需关注'; }

            const barColor = pScore > 60 ? '#ef4444' : pScore > 30 ? '#f59e0b' : '#10b981';

            paragraphList.innerHTML += `
                <div class="paragraph-item" data-paragraph="${p.paragraph}">
                    <span class="paragraph-index">${p.paragraph}</span>
                    <div class="paragraph-bar">
                        <div class="paragraph-fill" style="width:0%;background:${barColor}" data-target="${pScore}"></div>
                    </div>
                    <span class="paragraph-score" style="color:${barColor}">${pScore}%</span>
                    <span class="paragraph-risk ${riskClass}">${riskText}</span>
                </div>
            `;
        });

        // Animate bars after a short delay
        setTimeout(() => {
            document.querySelectorAll('.paragraph-fill').forEach(el => {
                el.style.width = el.dataset.target + '%';
            });
        }, 300);
    }

    // Store price for payment
    document.getElementById('pay-word-count').textContent = `${wordCount} 词`;
    document.getElementById('pay-price').textContent = `¥${price.toFixed(2)}`;
    document.getElementById('pay-btn-price').textContent = price.toFixed(2);
}

/* ========== SCROLLING ========== */
function scrollToUpload() {
    document.getElementById('upload-area').scrollIntoView({ behavior: 'smooth' });
}

function scrollToResults() {
    document.getElementById('result-section').scrollIntoView({ behavior: 'smooth' });
}

/* ========== LOADING ========== */
function showLoading() {
    document.getElementById('loading-section').style.display = 'block';
    document.getElementById('result-section').style.display = 'none';
    document.getElementById('rewrite-section').style.display = 'none';

    // Animate loading steps
    let step = 1;
    const totalSteps = 4;
    const interval = setInterval(() => {
        document.getElementById(`step-${step}`).classList.add('completed');
        step++;
        if (step <= totalSteps) {
            document.getElementById(`step-${step}`).classList.add('active');
        }
        if (step > totalSteps) clearInterval(interval);
    }, 600);

    window.loadingInterval = interval;
    document.getElementById('step-1').classList.add('active');
}

function hideLoading() {
    document.getElementById('loading-section').style.display = 'none';
    if (window.loadingInterval) clearInterval(window.loadingInterval);
    // Reset steps
    for (let i = 1; i <= 4; i++) {
        const el = document.getElementById(`step-${i}`);
        el.classList.remove('active', 'completed');
    }
}

/* ========== AUTH ========== */
let currentUser = null;

// Check login status on page load (eager init to avoid race with orders.html)
let loginStatusPromise = checkLoginStatus();

async function checkLoginStatus() {
    try {
        const resp = await fetch('/api/me');
        if (resp.ok) {
            const data = await resp.json();
            currentUser = data.user;
            updateNavbar(currentUser);
        } else {
            currentUser = null;
            updateNavbar(null);
        }
    } catch (err) {
        currentUser = null;
        updateNavbar(null);
    }
}

function updateNavbar(user) {
    const loginBtn = document.getElementById('login-btn');
    const logoutBtn = document.getElementById('logout-btn');
    const ordersLink = document.getElementById('orders-link');
    const navUser = document.getElementById('nav-user');

    if (user) {
        loginBtn.style.display = 'none';
        logoutBtn.style.display = 'inline-flex';
        ordersLink.style.display = 'inline-block';
        navUser.style.display = 'inline-block';
        navUser.textContent = user.email;
    } else {
        loginBtn.style.display = 'inline-flex';
        logoutBtn.style.display = 'none';
        ordersLink.style.display = 'none';
        navUser.style.display = 'none';
    }
}

function showAuthModal(tab) {
    const modal = document.getElementById('auth-modal');
    modal.style.display = 'flex';
    document.body.style.overflow = 'hidden';
    switchAuthTab(tab);
    // Focus the close button for accessibility
    const closeBtn = modal.querySelector('.modal-close');
    if (closeBtn) setTimeout(() => closeBtn.focus(), 100);
}

function closeAuthModal() {
    const modal = document.getElementById('auth-modal');
    modal.style.display = 'none';
    document.body.style.overflow = '';
    // Clear errors
    document.getElementById('login-error').textContent = '';
    document.getElementById('register-error').textContent = '';
    document.getElementById('register-success').textContent = '';
    // Return focus to login button (only if visible)
    const loginBtn = document.getElementById('login-btn');
    if (loginBtn && loginBtn.style.display !== 'none') loginBtn.focus();
}

// Close auth modal on overlay click
const authModalEl = document.getElementById('auth-modal');
if (authModalEl) {
    authModalEl.addEventListener('click', (e) => {
        if (e.target === e.currentTarget) closeAuthModal();
    });
}

function switchAuthTab(tab) {
    // Update tabs
    document.querySelectorAll('.auth-tab').forEach(t => t.classList.remove('active'));
    document.getElementById(`auth-tab-${tab}`).classList.add('active');

    // Show/hide forms
    document.getElementById('auth-form-login').style.display = tab === 'login' ? 'flex' : 'none';
    document.getElementById('auth-form-register').style.display = tab === 'register' ? 'flex' : 'none';

    // Clear errors
    document.getElementById('login-error').textContent = '';
    document.getElementById('register-error').textContent = '';
    document.getElementById('register-success').textContent = '';
}

async function handleLogin() {
    const email = document.getElementById('login-email').value.trim();
    const password = document.getElementById('login-password').value;
    const errorEl = document.getElementById('login-error');

    errorEl.textContent = '';

    if (!email || !password) {
        errorEl.textContent = '请填写邮箱和密码';
        return;
    }

    try {
        const resp = await _csrfFetch('/api/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password })
        });
        const data = await resp.json();

        if (data.error) {
            errorEl.textContent = data.error;
            return;
        }

        currentUser = data.user;
        updateNavbar(currentUser);
        closeAuthModal();
        showToast(`欢迎回来，${currentUser.email}`, 'success');

        // Check for pending paid analysis after login
        const pendingPaid = sessionStorage.getItem('pendingPaidAnalysis');
        if (pendingPaid) {
            sessionStorage.removeItem('pendingPaidAnalysis');
            const pendingInfo = JSON.parse(sessionStorage.getItem('pendingPaymentInfo') || '{}');
            sessionStorage.removeItem('pendingPaymentInfo');
            const wc = pendingInfo.wordCount || 0;
            const pr = pendingInfo.price || 0;
            setTimeout(() => {
                showPaymentModal();
                document.getElementById('pay-word-count').textContent = wc + ' 词';
                document.getElementById('pay-price').textContent = '¥' + pr;
                document.getElementById('pay-btn-price').textContent = pr;
                document.getElementById('pay-btn').disabled = true;
                document.getElementById('pay-btn').innerHTML = '⏳ 正在生成支付订单...';
                document.getElementById('payment-qr-section').style.display = 'none';
                createPaymentOrder(wc, pr, pendingInfo.mode || 'academic');
            }, 500);
        }

        // Clear login fields
        document.getElementById('login-email').value = '';
        document.getElementById('login-password').value = '';
    } catch (err) {
        errorEl.textContent = '登录失败：' + getNetworkErrorMessage(err);
        console.error('登录出错:', err);
    }
}

async function handleRegister() {
    const email = document.getElementById('register-email').value.trim();
    const password = document.getElementById('register-password').value;
    const confirm = document.getElementById('register-confirm').value;
    const errorEl = document.getElementById('register-error');
    const successEl = document.getElementById('register-success');

    errorEl.textContent = '';
    successEl.textContent = '';

    if (!email || !password || !confirm) {
        errorEl.textContent = '请填写所有字段';
        return;
    }

    if (password !== confirm) {
        errorEl.textContent = '两次密码输入不一致';
        return;
    }

    if (password.length < 6) {
        errorEl.textContent = '密码长度至少 6 位';
        return;
    }

    // Check password complexity: must include uppercase, lowercase, and digit
    if (!/[A-Z]/.test(password)) {
        errorEl.textContent = '密码必须包含至少一个大写字母';
        return;
    }
    if (!/[a-z]/.test(password)) {
        errorEl.textContent = '密码必须包含至少一个小写字母';
        return;
    }
    if (!/[0-9]/.test(password)) {
        errorEl.textContent = '密码必须包含至少一个数字';
        return;
    }

    try {
        const resp = await _csrfFetch('/api/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password, confirm_password: confirm })
        });
        const data = await resp.json();

        if (data.error) {
            errorEl.textContent = data.error;
            return;
        }

        currentUser = data.user;
        updateNavbar(currentUser);
        closeAuthModal();
        showToast(`注册成功！欢迎，${currentUser.email}`, 'success');

        // Check for pending paid analysis after register
        const pendingPaid = sessionStorage.getItem('pendingPaidAnalysis');
        if (pendingPaid) {
            sessionStorage.removeItem('pendingPaidAnalysis');
            const pendingInfo = JSON.parse(sessionStorage.getItem('pendingPaymentInfo') || '{}');
            sessionStorage.removeItem('pendingPaymentInfo');
            const wc = pendingInfo.wordCount || 0;
            const pr = pendingInfo.price || 0;
            setTimeout(() => {
                showPaymentModal();
                document.getElementById('pay-word-count').textContent = wc + ' 词';
                document.getElementById('pay-price').textContent = '¥' + pr;
                document.getElementById('pay-btn-price').textContent = pr;
                document.getElementById('pay-btn').disabled = true;
                document.getElementById('pay-btn').innerHTML = '⏳ 正在生成支付订单...';
                document.getElementById('payment-qr-section').style.display = 'none';
                createPaymentOrder(wc, pr, pendingInfo.mode || 'academic');
            }, 500);
        }

        // Clear register fields
        document.getElementById('register-email').value = '';
        document.getElementById('register-password').value = '';
        document.getElementById('register-confirm').value = '';
    } catch (err) {
        errorEl.textContent = '注册失败：' + getNetworkErrorMessage(err);
        console.error('注册出错:', err);
    }
}

/* ========== PASSWORD VISIBILITY TOGGLE ========== */
function togglePasswordVisibility(inputId, btn) {
    const input = document.getElementById(inputId);
    if (!input) return;
    const isPassword = input.type === 'password';
    input.type = isPassword ? 'text' : 'password';
    // Toggle eye icons
    const openIcon = btn.querySelector('.eye-open');
    const closedIcon = btn.querySelector('.eye-closed');
    if (openIcon && closedIcon) {
        openIcon.style.display = isPassword ? 'none' : '';
        closedIcon.style.display = isPassword ? '' : 'none';
    }
}

async function logout() {
    try {
        await _csrfFetch('/api/logout', { method: 'POST' });
        currentUser = null;
        updateNavbar(null);
        showToast('已退出登录', 'info');
    } catch (err) {
        showToast('退出失败', 'error');
    }
}

/* ========== PAYMENT ========== */
function showPaymentModal() {
    const modal = document.getElementById('payment-modal');
    if (modal) {
        modal.style.display = 'flex';
        document.body.style.overflow = 'hidden';
        // Focus the close button for accessibility
        const closeBtn = modal.querySelector('.modal-close');
        if (closeBtn) setTimeout(() => closeBtn.focus(), 100);
    }
}

function closePaymentModal() {
    const modal = document.getElementById('payment-modal');
    if (modal) {
        modal.style.display = 'none';
        document.body.style.overflow = '';

        // Restore default payment UI state
        const payBtn = document.getElementById('pay-btn');
        if (payBtn) {
            payBtn.style.display = '';
            payBtn.disabled = false;
            payBtn.innerHTML = '💳 确认支付 ¥<span id="pay-btn-price">0.00</span>';
        }
        const qrSection = document.getElementById('payment-qr-section');
        if (qrSection) qrSection.style.display = 'none';

        // Return focus to the element that triggered the modal
        const rewriteBtn = document.getElementById('rewrite-btn');
        if (rewriteBtn) rewriteBtn.focus();
    }
}

// Close modal on overlay click
const paymentModal = document.getElementById('payment-modal');
if (paymentModal) {
    paymentModal.addEventListener('click', (e) => {
        if (e.target === e.currentTarget) closePaymentModal();
    });
}

// Global Escape key handler - closes any visible modal
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        const paymentModalEl = document.getElementById('payment-modal');
        const authModalEl = document.getElementById('auth-modal');
        if (paymentModalEl && paymentModalEl.style.display === 'flex') {
            closePaymentModal();
        } else if (authModalEl && authModalEl.style.display === 'flex') {
            closeAuthModal();
        }
    }
});

async function previewRewrite() {
    const text = getCurrentText();
    if (!text) {
        showToast('没有可预览的文本', 'error');
        return;
    }

    document.getElementById('preview-btn').disabled = true;
    document.getElementById('preview-btn').textContent = '⏳ 正在预览...';

    try {
        const resp = await _csrfFetch('/api/preview-rewrite', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text })
        });
        const data = await resp.json();

        if (data.error) {
            showToast(data.error, 'error');
            return;
        }

        document.getElementById('preview-result').style.display = 'block';
        document.getElementById('preview-original-text').textContent = data.original_excerpt;
        document.getElementById('preview-rewritten-text').textContent = data.rewritten_excerpt;
        document.getElementById('preview-orig-score').textContent = `${data.original_score}%`;
        document.getElementById('preview-new-score').textContent = `${data.rewritten_score}%`;
    } catch (err) {
        showToast(getNetworkErrorMessage(err), 'error');
        console.error('预览出错:', err);
    } finally {
        document.getElementById('preview-btn').disabled = false;
        document.getElementById('preview-btn').textContent = '👁️ 免费预览改写效果';
    }
}

async function confirmPayment() {
    // Check login first
    if (!currentUser) {
        showToast('请先登录后再支付', 'error');
        showAuthModal('login');
        return;
    }

    const btn = document.getElementById('pay-btn');
    btn.disabled = true;
    btn.textContent = '⏳ 处理中...';

    // Show loading overlay inside the modal
    const modal = document.getElementById('payment-modal');
    const overlay = document.createElement('div');
    overlay.className = 'modal-loading-overlay';
    overlay.innerHTML = '<div class="modal-loading-spinner"></div><div class="modal-loading-text">正在处理支付...</div>';
    if (modal) modal.appendChild(overlay);

    try {
        // Step 1: Initiate rewrite
        const text = getCurrentText();
        if (!text) {
            showToast('没有可改写的文本', 'error');
            if (overlay.parentNode) overlay.remove();
            btn.disabled = false;
            btn.innerHTML = '💳 确认支付 ¥<span id="pay-btn-price">' + document.getElementById('pay-price').textContent.replace('¥', '') + '</span>';
            return;
        }

        const resp1 = await _csrfFetch('/api/rewrite', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text, mode: 'academic' })
        });
        overlay.querySelector('.modal-loading-text').textContent = '正在确认支付...';
        const data1 = await resp1.json();
        if (data1.error) {
            if (data1.login_required) {
                showToast('请先登录后再支付', 'error');
                if (overlay.parentNode) overlay.remove();
                closePaymentModal();
                showAuthModal('login');
                return;
            }
            showToast(data1.error, 'error');
            if (overlay.parentNode) overlay.remove();
            btn.disabled = false;
            btn.innerHTML = '💳 确认支付 ¥<span id="pay-btn-price">' + document.getElementById('pay-price').textContent.replace('¥', '') + '</span>';
            return;
        }

        // Step 2: Generate simulated payment token and confirm
        const paymentToken = 'PAY-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 8).toUpperCase();
        const resp2 = await _csrfFetch('/api/confirm-payment', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ payment_token: paymentToken })
        });
        const data2 = await resp2.json();
        if (data2.error) {
            if (data2.login_required) {
                showToast('请先登录后再支付', 'error');
                if (overlay.parentNode) overlay.remove();
                closePaymentModal();
                showAuthModal('login');
                return;
            }
            showToast(data2.error, 'error');
            if (overlay.parentNode) overlay.remove();
            btn.disabled = false;
            btn.innerHTML = '💳 确认支付 ¥<span id="pay-btn-price">' + document.getElementById('pay-price').textContent.replace('¥', '') + '</span>';
            return;
        }

        // Close modal (closePaymentModal will clean up)
        if (overlay.parentNode) overlay.remove();
        closePaymentModal();
        btn.disabled = false;
        btn.innerHTML = '💳 确认支付 ¥<span id="pay-btn-price">' + document.getElementById('pay-price').textContent.replace('¥', '') + '</span>';

        // Show rewrite result
        displayRewriteResult(data2);

    } catch (err) {
        showToast(getNetworkErrorMessage(err), 'error');
        console.error('处理支付出错:', err);
        if (overlay.parentNode) overlay.remove();
        btn.disabled = false;
        btn.innerHTML = '💳 确认支付 ¥<span id="pay-btn-price">' + document.getElementById('pay-price').textContent.replace('¥', '') + '</span>';
    }
}

function getCurrentText() {
    // Text is always in textarea now (file upload also fills it after analysis)
    const text = textInput.value.trim();
    return text || null;
}

/* ========== REWRITE RESULT ========== */
let _rewriteOriginalText = '';
let _rewriteNewText = '';

/**
 * Word-level diff using simplified LCS algorithm.
 * Returns array of { type: 'added'|'deleted'|'unchanged', text: string }
 */
function computeWordDiff(original, modified) {
    // Tokenize into words + spaces/punctuation
    function tokenize(text) {
        return text.match(/\S+|\s+/g) || [];
    }

    const origTokens = tokenize(original);
    const newTokens = tokenize(modified);
    const m = origTokens.length;
    const n = newTokens.length;

    // LCS DP (limit size to avoid performance issues on very long texts)
    const MAX_LCS = 3000;
    let useLCS = m <= MAX_LCS && n <= MAX_LCS;

    if (useLCS) {
        // Build LCS table
        const dp = Array.from({ length: m + 1 }, () => new Int32Array(n + 1));
        for (let i = 1; i <= m; i++) {
            for (let j = 1; j <= n; j++) {
                if (origTokens[i - 1] === newTokens[j - 1]) {
                    dp[i][j] = dp[i - 1][j - 1] + 1;
                } else {
                    dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1]);
                }
            }
        }

        // Backtrack to produce diff
        const result = [];
        let i = m, j = n;
        while (i > 0 || j > 0) {
            if (i > 0 && j > 0 && origTokens[i - 1] === newTokens[j - 1]) {
                result.push({ type: 'unchanged', text: origTokens[i - 1] });
                i--; j--;
            } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
                result.push({ type: 'added', text: newTokens[j - 1] });
                j--;
            } else {
                result.push({ type: 'deleted', text: origTokens[i - 1] });
                i--;
            }
        }
        result.reverse();
        return result;
    } else {
        // Fallback for very long texts: just show as-is
        return [{ type: 'unchanged', text: modified }];
    }
}

/**
 * Render diff as HTML
 */
function renderDiffHTML(diff) {
    return diff.map(item => {
        const escaped = escapeHtml(item.text);
        if (item.type === 'added') {
            return `<span class="diff-added">${escaped}</span>`;
        } else if (item.type === 'deleted') {
            return `<span class="diff-deleted">${escaped}</span>`;
        }
        return escaped;
    }).join('');
}

/**
 * Toggle between plain text and diff view
 */
function toggleDiffView() {
    const checked = document.getElementById('diff-toggle-checkbox').checked;
    const container = document.getElementById('rewrite-new-text');
    const legend = document.getElementById('diff-legend');

    if (checked) {
        const diff = computeWordDiff(_rewriteOriginalText, _rewriteNewText);
        container.innerHTML = renderDiffHTML(diff);
        legend.style.display = 'flex';
    } else {
        container.textContent = _rewriteNewText;
        legend.style.display = 'none';
    }
}

function displayRewriteResult(data) {
    const section = document.getElementById('rewrite-section');
    section.style.display = 'block';
    document.getElementById('result-section').style.display = 'none';

    document.getElementById('rewrite-order-id').textContent = `订单号：${data.order_id}`;

    // Store latest result for download
    // Note: PDF originals are downloaded as DOCX (backend auto-converts)
    let origFormat = data.original_format || sessionStorage.getItem('lastOriginalFormat') || 'txt';
    if (origFormat === 'pdf') origFormat = 'docx';
    latestResult = {
        orderId: data.order_id,
        originalFormat: origFormat,
        originalFilename: data.original_filename || sessionStorage.getItem('lastOriginalFilename') || 'humanized'
    };

    // Update download button text with format hint
    const fmt = latestResult.originalFormat;
    const downloadBtn = document.getElementById('download-btn');
    downloadBtn.textContent = `⬇️ 下载为 ${fmt.toUpperCase()}`;

    // Original
    document.getElementById('orig-score-badge').textContent = `${data.original.ai_score}%`;
    document.getElementById('orig-score-badge').style.background =
        data.original.ai_score > 40 ? '#fde8e8' : data.original.ai_score > 20 ? '#fef3c7' : '#d1fae5';
    document.getElementById('orig-risk').textContent = data.original.risk_level;
    document.getElementById('rewrite-original-text').textContent = data.original.text;

    // Rewritten
    document.getElementById('new-score-badge').textContent = `${data.rewritten.ai_score}%`;
    document.getElementById('new-risk').textContent = data.rewritten.risk_level;
    document.getElementById('improvement-badge').textContent = `↓ ${data.improvement}%`;
    document.getElementById('improvement-badge').style.background =
        data.improvement > 30 ? '#10b981' : data.improvement > 15 ? '#f59e0b' : '#6b7280';

    // Store raw texts for diff comparison
    _rewriteOriginalText = data.original.text;
    _rewriteNewText = data.rewritten.text;
    document.getElementById('rewrite-new-text').textContent = _rewriteNewText;

    // Reset diff toggle
    document.getElementById('diff-toggle-checkbox').checked = false;
    document.getElementById('diff-legend').style.display = 'none';

    showToast(`✅ 改写完成！AI 率从 ${data.original.ai_score}% 降至 ${data.rewritten.ai_score}%`, 'success');

    setTimeout(() => {
        section.scrollIntoView({ behavior: 'smooth' });
    }, 300);
}

/* ========== DOWNLOAD ========== */
function downloadResult() {
    if (latestResult) {
        // Download via server API for format-aware output
        const fmt = latestResult.originalFormat;
        window.open(`/api/download/${latestResult.orderId}?format=${fmt}`, '_blank');
    } else {
        // Fallback: client-side text download
        const text = document.getElementById('rewrite-new-text').textContent;
        const blob = new Blob([text], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'humanized_text.txt';
        a.click();
        URL.revokeObjectURL(url);
    }
}

/* ========== UTILITIES ========== */
function copyResult() {
    const text = document.getElementById('rewrite-new-text').textContent;
    navigator.clipboard.writeText(text).then(() => {
        showToast('已复制到剪贴板', 'success');
    });
}

function resetAnalysis() {
    document.getElementById('result-section').style.display = 'none';
    document.getElementById('rewrite-section').style.display = 'none';
    uploadedFile = null;
    latestResult = null;
    dropZone.classList.remove('has-file');
    dropZone.querySelector('.drop-text').textContent = '拖拽文档到此处，或 点击选择文件';
    textInput.value = '';
    fileInput.value = '';
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

function resetAll() {
    resetAnalysis();
}

function animateCounter(elementId, start, end, duration) {
    const el = document.getElementById(elementId);
    const startTime = performance.now();

    function update(currentTime) {
        const elapsed = currentTime - startTime;
        const progress = Math.min(elapsed / duration, 1);
        // Ease out cubic
        const eased = 1 - Math.pow(1 - progress, 3);
        const current = start + (end - start) * eased;
        el.textContent = Math.round(current);

        if (progress < 1) {
            requestAnimationFrame(update);
        }
    }

    requestAnimationFrame(update);
}

/* ========== NETWORK ERROR HELPER ========== */
function getNetworkErrorMessage(err) {
    if (err instanceof TypeError && err.message === 'Failed to fetch') {
        return '网络连接失败，请检查网络后重试';
    }
    if (err instanceof TypeError && err.message.includes('NetworkError')) {
        return '网络连接失败，请检查网络后重试';
    }
    if (err instanceof SyntaxError) {
        return '服务器响应格式异常，请重试';
    }
    if (err.name === 'AbortError') {
        return '请求超时，请重试';
    }
    if (err.message && err.message.includes('timeout')) {
        return '请求超时，请重试';
    }
    if (err.message && err.message.includes('HTTP')) {
        return '服务器暂时不可用，请稍后重试';
    }
    // Fallback: return a generic message that still includes the error name for debugging
    return '请求失败，请重试';
}

/* ========== TOAST ========== */
function showToast(message, type = 'info') {
    const existing = document.querySelector('.toast');
    if (existing) existing.remove();

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;

    document.body.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

/* ========== FAQ ACCORDION ========== */
document.querySelectorAll('.faq-question').forEach(btn => {
    btn.addEventListener('click', () => {
        const item = btn.parentElement;
        const isOpen = item.classList.contains('open');

        // Close all
        document.querySelectorAll('.faq-item').forEach(i => i.classList.remove('open'));

        // Toggle current
        if (!isOpen) item.classList.add('open');
    });
});

/* ========== KEYBOARD SHORTCUT ========== */
if (textInput) {
    textInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
            analyzeText();
        }
    });
}

/* ========== PARAGRAPH CLICK (Event Delegation) ========== */
const paragraphListEl = document.getElementById('paragraph-list');
if (paragraphListEl) {
    paragraphListEl.addEventListener('click', (e) => {
        const item = e.target.closest('.paragraph-item');
        if (item) {
            const index = item.dataset.paragraph;
            showToast('段落详情功能即将上线', 'info');
        }
    });
}

function showDetail(paragraphIndex) {
    showToast('段落详情功能即将上线', 'info');
}

/* ========== ORDERS PAGE ========== */
// These functions are used by orders.html
let currentOrderPage = 1;
let orderTotalPages = 1;

async function loadOrders(page) {
    // Ensure login status is fresh before loading orders
    if (!currentUser) {
        await checkLoginStatus();
        if (!currentUser) {
            window.location.href = '/';
            return;
        }
    }

    try {
        const resp = await fetch(`/api/orders?page=${page}&per_page=10`);
        if (resp.status === 401) {
            currentUser = null;
            updateNavbar(null);
            window.location.href = '/';
            return;
        }
        const data = await resp.json();

        if (data.error) {
            showToast(data.error, 'error');
            return;
        }

        currentOrderPage = data.page;
        orderTotalPages = data.pages;
        renderOrders(data.orders, data.total, data.page, data.pages);
    } catch (err) {
        showToast(getNetworkErrorMessage(err), 'error');
        console.error('加载订单失败:', err);
    }
}

function renderOrders(orders, total, page, pages) {
    const container = document.getElementById('orders-list');
    const emptyState = document.getElementById('orders-empty');
    const pagination = document.getElementById('orders-pagination');

    if (!container) return; // Not on orders page

    if (!orders || orders.length === 0) {
        container.innerHTML = '';
        if (emptyState) emptyState.style.display = 'block';
        if (pagination) pagination.style.display = 'none';
        return;
    }

    if (emptyState) emptyState.style.display = 'none';
    if (pagination) pagination.style.display = 'flex';

    container.innerHTML = orders.map(o => {
        const origScore = o.original_score || 0;
        const rewScore = o.rewritten_score || 0;
        const improvement = (origScore - rewScore).toFixed(1);
        const improved = improvement > 0 ? 'improved' : 'worsened';
        const improvementSign = improvement > 0 ? '↓' : '↑';

        const createdDate = o.created_at ? new Date(o.created_at).toLocaleDateString('zh-CN') : '';
        const formatLabel = (o.original_format === 'pdf' ? 'DOCX' : (o.original_format || 'txt').toUpperCase());

        return `
            <div class="order-card">
                <div class="order-info">
                    <div class="order-id-text">${o.order_id}</div>
                    <div class="order-meta">
                        <span>📅 ${createdDate}</span>
                        <span>📝 ${o.word_count || 0} 词</span>
                        <span class="order-format-badge">${formatLabel}</span>
                        <span class="order-score-change ${improved}">
                            ${improvementSign} ${Math.abs(improvement)}%
                        </span>
                    </div>
                </div>
                <div class="order-actions">
                    <button class="btn btn-outline btn-sm" onclick="viewOrderDetail('${o.order_id}')">查看详情</button>
                    <button class="btn btn-outline btn-sm" onclick="reDownload('${o.order_id}', '${o.original_format === 'pdf' ? 'docx' : (o.original_format || 'txt')}')">⬇️ 下载</button>
                    <button class="btn btn-primary btn-sm" onclick="reHumanize('${o.order_id}')">🔄 再次改写</button>
                </div>
            </div>
        `;
    }).join('');

    // Update pagination
    const pageInfo = document.getElementById('page-info');
    if (pageInfo) {
        pageInfo.textContent = `第 ${page} / ${pages} 页`;
    }

    const prevBtn = document.getElementById('page-prev');
    const nextBtn = document.getElementById('page-next');
    if (prevBtn) prevBtn.disabled = page <= 1;
    if (nextBtn) nextBtn.disabled = page >= pages;
}

function goToPage(page) {
    if (page < 1 || page > orderTotalPages) return;
    loadOrders(page);
}

async function viewOrderDetail(orderId) {
    try {
        const resp = await fetch(`/api/orders/${orderId}`);
        if (!resp.ok) {
            showToast('获取订单详情失败', 'error');
            return;
        }
        const data = await resp.json();
        const order = data.order;

        const origScore = (order.original_score || 0).toFixed(1);
        const rewScore = (order.rewritten_score || 0).toFixed(1);
        const improvement = (order.original_score - order.rewritten_score).toFixed(1);

        const createdDate = order.created_at ? new Date(order.created_at).toLocaleString('zh-CN') : '';
        const expiresDate = order.expires_at ? new Date(order.expires_at).toLocaleString('zh-CN') : '';

        // Show detail in a modal-like overlay using the existing modal system
        const modalBody = `
            <div class="modal-icon">📋</div>
            <h3 class="modal-title">${order.order_id}</h3>
            <div class="order-detail-row">
                <span class="order-detail-label">原文 AI 率</span>
                <span class="order-detail-value">${origScore}%</span>
            </div>
            <div class="order-detail-row">
                <span class="order-detail-label">改写后 AI 率</span>
                <span class="order-detail-value">${rewScore}%</span>
            </div>
            <div class="order-detail-row">
                <span class="order-detail-label">改善</span>
                <span class="order-detail-value" style="color:var(--success)">↓ ${improvement}%</span>
            </div>
            <div class="order-detail-row">
                <span class="order-detail-label">词数</span>
                <span class="order-detail-value">${order.word_count || 0} 词</span>
            </div>
            <div class="order-detail-row">
                <span class="order-detail-label">格式</span>
                <span class="order-detail-value">${order.original_format === 'pdf' ? 'DOCX (原PDF)' : (order.original_format || 'txt').toUpperCase()}</span>
            </div>
            <div class="order-detail-row">
                <span class="order-detail-label">创建时间</span>
                <span class="order-detail-value">${createdDate}</span>
            </div>
            <div class="order-detail-row">
                <span class="order-detail-label">过期时间</span>
                <span class="order-detail-value">${expiresDate}</span>
            </div>

            <h4 style="margin-top:20px;margin-bottom:8px;font-size:1rem;text-align:left;">原文预览</h4>
            <div class="order-detail-text">${escapeHtml(order.original_text || '').slice(0, 500)}${(order.original_text || '').length > 500 ? '...' : ''}</div>

            <h4 style="margin-bottom:8px;font-size:1rem;text-align:left;">改写后预览</h4>
            <div class="order-detail-text">${escapeHtml(order.rewritten_text || '').slice(0, 500)}${(order.rewritten_text || '').length > 500 ? '...' : ''}</div>

            <div class="order-detail-actions">
                <button class="btn btn-primary btn-full" onclick="closeDetailModal(); reDownload('${order.order_id}', '${order.original_format === 'pdf' ? 'docx' : (order.original_format || 'txt')}')">⬇️ 下载</button>
            </div>
        `;

        showDetailModal(modalBody);

    } catch (err) {
        showToast(getNetworkErrorMessage(err), 'error');
        console.error('获取订单详情失败:', err);
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function showDetailModal(html) {
    // Create a temporary detail modal
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.style.display = 'flex';
    overlay.innerHTML = `
        <div class="modal" style="max-width:600px;">
            <button class="modal-close" onclick="closeDetailModal()">&times;</button>
            <div class="modal-body" style="text-align:left;">${html}</div>
        </div>
    `;
    overlay.id = 'detail-modal-overlay';
    overlay.addEventListener('click', (e) => {
        if (e.target === e.currentTarget) closeDetailModal();
    });
    document.body.appendChild(overlay);
    document.body.style.overflow = 'hidden';
}

function closeDetailModal() {
    const overlay = document.getElementById('detail-modal-overlay');
    if (overlay) {
        overlay.remove();
        document.body.style.overflow = '';
    }
}

function reDownload(orderId, format) {
    window.open(`/api/download/${orderId}?format=${format || 'txt'}`, '_blank');
}

async function reHumanize(orderId) {
    const mode = 'academic'; // Default mode
    try {
        showToast('⏳ 正在重新改写...', 'info');
        const resp = await _csrfFetch(`/api/orders/${orderId}/rehumanize`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mode })
        });
        const data = await resp.json();

        if (data.error) {
            showToast(data.error, 'error');
            return;
        }

        showToast(`✅ 改写完成！AI 率降至 ${data.rewritten.ai_score}%`, 'success');

        // Navigate to home page and show result
        sessionStorage.setItem('rehumanizeResult', JSON.stringify(data));
        window.location.href = '/';

    } catch (err) {
        showToast(getNetworkErrorMessage(err), 'error');
        console.error('改写出错:', err);
    }
}

