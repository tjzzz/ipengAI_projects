/**
 * common.js — shared utilities, globals, and helpers
 * Loaded first; all other scripts depend on this.
 */

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
    return _csrfFetch('/api/extracted-text', { method: 'GET' })
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

/* ========== SHARED STATE ========== */
let uploadedFile = null;

/* Store latest result info for download */
let latestResult = null;

/* ========== GET CURRENT TEXT ========== */
function getCurrentText() {
    const text = textInput ? textInput.value.trim() : '';
    if (text) return text;
    const extractedText = sessionStorage.getItem('lastExtractedText');
    return extractedText || null;
}

/* ========== ESCAPE HTML ========== */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/* ========== WORD DIFF (LCS algorithm) ========== */
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

/* ========== RESET ========== */
function resetAnalysis() {
    document.getElementById('result-section').style.display = 'none';
    document.getElementById('rewrite-section').style.display = 'none';
    uploadedFile = null;
    latestResult = null;
    if (dropZone) {
        dropZone.classList.remove('has-file');
        const dropTextEl = dropZone.querySelector('.drop-text');
        if (dropTextEl) dropTextEl.textContent = '拖拽文档到此处，或 点击选择文件';
    }
    if (textInput) textInput.value = '';
    if (fileInput) fileInput.value = '';
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

function resetAll() {
    resetAnalysis();
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

/* ========== COPY ========== */
function copyResult() {
    const text = document.getElementById('rewrite-new-text').textContent;
    navigator.clipboard.writeText(text).then(() => {
        showToast('已复制到剪贴板', 'success');
    });
}

/* ========== ANIMATE COUNTER ========== */
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

/* (paragraph-list removed — no longer shown in results) */
