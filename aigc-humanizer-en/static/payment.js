/**
 * payment.js — payment flow, QR code, polling, rewrite result display
 * Depends on: common.js, auth.js
 * Only loaded on index page (not orders page).
 */

/* ========== PAYMENT CONFIG ========== */
let paymentConfig = {
    adapter_type: 'mock',
    is_mock: true
};

async function fetchPaymentConfig() {
    try {
        const resp = await fetch('/api/payment-config');
        const data = await resp.json();
        if (data.adapter_type !== undefined) {
            paymentConfig = data;
        }
    } catch (err) {
        console.error('Failed to fetch payment config:', err);
        // Default to mock mode if fetch fails
        paymentConfig = { adapter_type: 'mock', is_mock: true };
    }
}

/* ========== PAYMENT MODAL ========== */
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

function showPaymentModalWithAiScore(wordCount, price, aiScore) {
    // Update display values
    document.getElementById('pay-word-count').textContent = `${wordCount} 词`;
    document.getElementById('pay-price').textContent = price === 0 ? '免费' : `¥${price.toFixed(2)}`;

    // Update AI score display
    const aiScoreDisplay = document.getElementById('ai-score-display');
    if (aiScoreDisplay) {
        aiScoreDisplay.textContent = `${aiScore}%`;
        // Set color based on score
        if (aiScore < 20) {
            aiScoreDisplay.style.color = '#10b981';
        } else if (aiScore < 40) {
            aiScoreDisplay.style.color = '#f59e0b';
        } else if (aiScore < 60) {
            aiScoreDisplay.style.color = '#f97316';
        } else {
            aiScoreDisplay.style.color = '#ef4444';
        }
    }

    // Show QR loading state while API generates the QR code
    showQRLoading();

    // Show modal
    showPaymentModal();
}

function closePaymentModal() {
    const modal = document.getElementById('payment-modal');
    if (modal) {
        modal.style.display = 'none';
        document.body.style.overflow = '';

        // Clear polling and QR expiry timers to prevent leaks
        if (pollInterval) {
            clearInterval(pollInterval);
            pollInterval = null;
        }
        if (qrExpiryInterval) {
            clearInterval(qrExpiryInterval);
            qrExpiryInterval = null;
        }

        // Restore default payment UI state
        const qrSection = document.getElementById('payment-qr-section');
        if (qrSection) qrSection.style.display = 'none';

        // Return focus to the element that triggered the modal
        const rewriteBtn = document.getElementById('rewrite-btn');
        if (rewriteBtn) rewriteBtn.focus();
    }
}

/* Close modal on overlay click */
const paymentModal = document.getElementById('payment-modal');
if (paymentModal) {
    paymentModal.addEventListener('click', (e) => {
        if (e.target === e.currentTarget) closePaymentModal();
    });
}

/* ========== QR LOADING HELPER ========== */
function showQRLoading() {
    const qs = document.getElementById('payment-qr-section');
    if (qs) qs.style.display = 'block';
    document.getElementById('qrcode-container').innerHTML = '';
    document.getElementById('poll-status').innerHTML = '⏳ 正在生成二维码...';
}

/* ========== QR CODE ========== */
let qrExpiryInterval = null;
let qrExpirySeconds = 600; // Default 10 minutes

function renderPaymentQR(order, wordCount, price) {
    const qrCode = order.qr_code;

    // Update payment modal content
    document.getElementById('pay-word-count').textContent = wordCount + ' 词';
    document.getElementById('pay-price').textContent = '¥' + parseFloat(price).toFixed(2);

    // Show QR section in modal
    const qrSection = document.getElementById('payment-qr-section');
    qrSection.style.display = 'block';

    // Reset poll status
    document.getElementById('poll-status').innerHTML = '⏳ 等待支付中...';
    document.getElementById('poll-timer').textContent = '';

    // Reset QR expiry timer
    qrExpirySeconds = order.expires_in || 600;
    startQRExpiryTimer();

    // Hide refresh button initially
    const refreshSection = document.getElementById('qr-refresh-section');
    if (refreshSection) {
        refreshSection.style.display = 'none';
    }

    // Show/hide mock payment button based on config
    const mockPaymentSection = document.getElementById('mock-payment-section');
    const mockBtn = document.getElementById('mock-pay-btn');

    if (paymentConfig.is_mock) {
        // Mock mode: show mock payment button
        if (mockPaymentSection) {
            mockPaymentSection.style.display = 'block';
        }
        if (mockBtn) {
            mockBtn.style.display = 'inline-block';
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
    } else {
        // Real payment mode: hide mock payment button
        if (mockPaymentSection) {
            mockPaymentSection.style.display = 'none';
        }
        if (mockBtn) {
            mockBtn.style.display = 'none';
        }
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

function startQRExpiryTimer() {
    if (qrExpiryInterval) {
        clearInterval(qrExpiryInterval);
    }

    const updateTimer = () => {
        const mm = String(Math.floor(qrExpirySeconds / 60)).padStart(2, '0');
        const ss = String(qrExpirySeconds % 60).padStart(2, '0');

        const expiryElement = document.getElementById('qr-expiry-timer');
        if (expiryElement) {
            if (qrExpirySeconds <= 60) {
                expiryElement.style.color = '#ef4444';
                expiryElement.innerHTML = `⏱️ 二维码即将过期: ${mm}:${ss}`;
            } else {
                expiryElement.style.color = '';
                expiryElement.innerHTML = `⏱️ 二维码有效期: ${mm}:${ss}`;
            }
        }

        if (qrExpirySeconds <= 0) {
            clearInterval(qrExpiryInterval);
            const refreshSection = document.getElementById('qr-refresh-section');
            if (refreshSection) {
                refreshSection.style.display = 'block';
            }
            const expiryElement = document.getElementById('qr-expiry-timer');
            if (expiryElement) {
                expiryElement.innerHTML = '❌ 二维码已过期，请点击下方按钮刷新';
                expiryElement.style.color = '#ef4444';
            }
            if (pollInterval) {
                clearInterval(pollInterval);
            }
        } else {
            qrExpirySeconds--;
        }
    };

    updateTimer();
    qrExpiryInterval = setInterval(updateTimer, 1000);
}

async function refreshQRCode() {
    const refreshBtn = document.getElementById('qr-refresh-btn');
    if (refreshBtn) {
        refreshBtn.disabled = true;
        refreshBtn.textContent = '刷新中...';
    }

    try {
        const wordCount = parseInt(document.getElementById('pay-word-count').textContent.replace(/[^0-9]/g, ''));
        const priceTxt = document.getElementById('pay-price').textContent.replace('¥', '').trim();
        const price = parseFloat(priceTxt);
        if (isNaN(price) || price <= 0) {
            showToast('价格异常，请重新检测', 'error');
            return;
        }

        await createPaymentOrder(wordCount, price, 'academic');

        showToast('二维码已刷新', 'success');
    } catch (err) {
        showToast('刷新失败，请重试', 'error');
        console.error('Failed to refresh QR code:', err);
    } finally {
        if (refreshBtn) {
            refreshBtn.disabled = false;
            refreshBtn.textContent = '🔄 刷新二维码';
        }
    }
}

/* ========== PAYMENT POLLING ========== */
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

            if (data.error) {
                // Order not found or access denied — stop polling
                clearInterval(pollInterval);
                document.getElementById('poll-status').innerHTML = '❌ ' + data.error;
                return;
            }

            if (data.payment_status === 'paid' || data.status === 'processing') {
                document.getElementById('poll-status').innerHTML = '✅ 支付成功，正在改写...';
            }

            if (data.status === 'completed' && data.success) {
                clearInterval(pollInterval);
                closePaymentModal();
                displayRewriteResult(data);
                showToast('改写完成！', 'success');
            }

            if (data.status === 'failed') {
                clearInterval(pollInterval);
                document.getElementById('poll-status').innerHTML = '❌ 改写失败，请稍后重试';
                showToast('改写失败，请稍后重试', 'error');
            } else if (data.payment_status === 'expired') {
                clearInterval(pollInterval);
                document.getElementById('poll-status').innerHTML = '⏰ 订单已超时，请重新检测';
                showToast('订单已超时', 'error');
            }
        } catch (err) {
            // Silently continue polling on error
            console.warn('Payment polling error:', err);
        }
    }, 3000);
}

/* ========== CREATE PAYMENT ORDER ========== */
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
        // Don't close modal, let user try again
    }
}

/* ========== LEGACY: PAID ANALYSIS ========== */
async function startPaidAnalysis() {
    if (!currentUser) {
        sessionStorage.setItem('pendingPaidAnalysis', 'true');
        showAuthModal('login');
        showToast('请先登录，登录后将自动跳转到付费检测', 'info');
        return;
    }
    createPaymentOrder();
}

/* ========== PREVIEW REWRITE ========== */
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

/* ========== DISPLAY REWRITE RESULT ========== */
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

/* ========== GLOBAL ESCAPE KEY ========== */
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

/* ========== DOM READY: INIT & RESTORE SESSION ========== */
document.addEventListener('DOMContentLoaded', () => {
    // Fetch payment config on page load
    fetchPaymentConfig();

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
            const _p2 = document.getElementById('pay-btn-price');
if (_p2) _p2.textContent = pr;
            showQRLoading();
            createPaymentOrder(wc, pr, pendingInfo.mode || 'academic');
        }, 800);
    }
});
