/**
 * main.js — main page flow: upload, analyze, results display
 *          + orders page functions
 * Depends on: common.js, auth.js, payment.js (for index page)
 * Loaded last.
 */

/* ========== FILE UPLOAD ========== */
/* Click to upload (only on main page) */
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
        showToast(data.error, 'error');
        return;
    }

    // Store format info for later download
    if (data.original_format) {
        sessionStorage.setItem('lastOriginalFormat', data.original_format);
        sessionStorage.setItem('lastOriginalFilename', data.original_filename || 'humanized');
    } else {
        sessionStorage.setItem('lastOriginalFormat', 'txt');
        sessionStorage.setItem('lastOriginalFilename', 'humanized');
    }

    // If uploaded via file, fetch extracted text on-demand for later rewrite use
    if (data.has_extracted_text) {
        _fetchExtractedText();
    }

    const wordCount = data.word_count;
    const price = data.price;
    const aiScore = data.analysis?.overall?.ai_score || 0;

    // Store AI score for display
    sessionStorage.setItem('lastAiScore', aiScore);

    if (price === 0) {
        // Free rewrite: directly call rewrite API without showing modal
        handleFreeRewrite();
    } else {
        // Paid rewrite: show payment modal and immediately create order + QR code
        showPaymentModalWithAiScore(wordCount, price, aiScore);
        // After modal is shown, immediately create payment order
        setTimeout(() => {
            createPaymentOrder(wordCount, price, 'academic');
        }, 300);
    }
}

/* ========== FREE REWRITE HANDLER ========== */
async function handleFreeRewrite() {
    showLoading();

    try {
        const text = getCurrentText();
        if (!text) {
            showToast('没有可改写的文本', 'error');
            hideLoading();
            return;
        }

        const resp = await _csrfFetch('/api/rewrite', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text, mode: 'academic' })
        });
        const data = await resp.json();

        hideLoading();

        if (data.error) {
            if (data.login_required) {
                showToast('请先登录', 'error');
                showAuthModal('login');
            } else {
                showToast(data.error, 'error');
            }
            return;
        }

        // Show rewrite result
        displayRewriteResult(data);
        showToast('改写完成！', 'success');
    } catch (err) {
        hideLoading();
        showToast(getNetworkErrorMessage(err), 'error');
        console.error('免费改写出错:', err);
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
        const _payBtnPrice = document.getElementById('pay-btn-price');
if (_payBtnPrice) _payBtnPrice.textContent = price;
        document.getElementById('payment-qr-section').style.display = 'none';

        createPaymentOrder(wordCount, price, 'academic');
    })();
}

/* ========== DISPLAY RESULTS ========== */
function displayResults(analysis, wordCount, price, overLimit = false) {
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
    document.getElementById('pay-price').textContent = price === 0 ? '免费' : `¥${price.toFixed(2)}`;
    const _p3 = document.getElementById('pay-btn-price');
if (_p3) _p3.textContent = price.toFixed(2);
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

/* ========== ORDERS PAGE ========== */
/* These functions are used by orders.html */
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
