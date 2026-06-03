/**
 * auth.js — authentication: login, register, logout, and navbar
 * Depends on: common.js
 */

/* ========== AUTH STATE ========== */
let currentUser = null;

/* Check login status on page load (eager init to avoid race with orders.html) */
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

/* ========== NAVBAR ========== */
function updateNavbar(user) {
    const loginBtn = document.getElementById('login-btn');
    const logoutBtn = document.getElementById('logout-btn');
    const ordersLink = document.getElementById('orders-link');
    const navUser = document.getElementById('nav-user');

    if (user) {
        if (loginBtn) loginBtn.style.display = 'none';
        if (logoutBtn) logoutBtn.style.display = 'inline-flex';
        if (ordersLink) ordersLink.style.display = 'inline-block';
        if (navUser) { navUser.style.display = 'inline-block'; navUser.textContent = user.email; }
    } else {
        if (loginBtn) loginBtn.style.display = 'inline-flex';
        if (logoutBtn) logoutBtn.style.display = 'none';
        if (ordersLink) ordersLink.style.display = 'none';
        if (navUser) navUser.style.display = 'none';
    }
}

/* ========== AUTH MODAL ========== */
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
    const loginErr = document.getElementById('login-error');
    const regErr = document.getElementById('register-error');
    const regSuccess = document.getElementById('register-success');
    if (loginErr) loginErr.textContent = '';
    if (regErr) regErr.textContent = '';
    if (regSuccess) regSuccess.textContent = '';
    // Return focus to login button (only if visible)
    const loginBtn = document.getElementById('login-btn');
    if (loginBtn && loginBtn.style.display !== 'none') loginBtn.focus();
}

/* Close auth modal on overlay click */
const authModalEl = document.getElementById('auth-modal');
if (authModalEl) {
    authModalEl.addEventListener('click', (e) => {
        if (e.target === e.currentTarget) closeAuthModal();
    });
}

function switchAuthTab(tab) {
    // Update tabs
    document.querySelectorAll('.auth-tab').forEach(t => t.classList.remove('active'));
    const tabEl = document.getElementById(`auth-tab-${tab}`);
    if (tabEl) tabEl.classList.add('active');

    // Show/hide forms
    const loginForm = document.getElementById('auth-form-login');
    const regForm = document.getElementById('auth-form-register');
    if (loginForm) loginForm.style.display = tab === 'login' ? 'flex' : 'none';
    if (regForm) regForm.style.display = tab === 'register' ? 'flex' : 'none';

    // Clear errors
    const loginErr = document.getElementById('login-error');
    const regErr = document.getElementById('register-error');
    const regSuccess = document.getElementById('register-success');
    if (loginErr) loginErr.textContent = '';
    if (regErr) regErr.textContent = '';
    if (regSuccess) regSuccess.textContent = '';
}

/* ========== LOGIN ========== */
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
                const _p2 = document.getElementById('pay-btn-price');
if (_p2) _p2.textContent = pr;
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

/* ========== REGISTER ========== */
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
                const _p2 = document.getElementById('pay-btn-price');
if (_p2) _p2.textContent = pr;
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

/* ========== LOGOUT ========== */
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

/* ========== DETAIL MODAL (used by orders page) ========== */
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
