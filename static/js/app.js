/* LINE Monitor - 前端互動 */

// === 通用 API 呼叫 ===
async function api(path, method = 'GET', body = null) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch(path, opts);
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || '未知錯誤');
    return data;
}

// === Toast 通知 ===
function toast(msg, type = 'info') {
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 3000);
}

// === 設定頁 ===
async function saveSettings() {
    const settings = {
        line_token: document.getElementById('line_token')?.value || '',
        webhook_url: document.getElementById('webhook_url')?.value || '',
        reminder_1: parseInt(document.getElementById('reminder_1')?.value || 1),
        reminder_2: parseInt(document.getElementById('reminder_2')?.value || 3),
        reminder_3: parseInt(document.getElementById('reminder_3')?.value || 6),
        patrol_interval: parseInt(document.getElementById('patrol_interval')?.value || 15),
        suppress_enabled: document.getElementById('suppress_enabled')?.checked ?? true,
        batch_enabled: document.getElementById('batch_enabled')?.checked ?? true,
        ai_model: document.getElementById('ai_model')?.value || 'glm-5.2',
        company_info: document.getElementById('company_info')?.value || '',
        auto_send: document.getElementById('auto_send')?.checked ?? false
    };
    try {
        await api('/api/settings', 'POST', settings);
        toast('設定已儲存', 'success');
    } catch (e) { toast(e.message, 'error'); }
}

async function testLine() {
    const token = document.getElementById('line_token')?.value;
    if (!token) { toast('請先輸入 token', 'error'); return; }
    try {
        const data = await api('/api/test-line', 'POST', { token });
        const el = document.getElementById('line-test-result');
        el.className = 'text-sm p-2 rounded bg-green-50 text-green-700';
        el.textContent = `✅ 連接成功：${data.bot_name || data.message}`;
        el.classList.remove('hidden');
        toast('LINE 連接成功', 'success');
    } catch (e) {
        const el = document.getElementById('line-test-result');
        el.className = 'text-sm p-2 rounded bg-red-50 text-red-700';
        el.textContent = `❌ 連接失敗：${e.message}`;
        el.classList.remove('hidden');
        toast('連接失敗', 'error');
    }
}

// === 成員管理 ===
async function addContact(role) {
    const name = document.getElementById(`${role}_name`)?.value.trim();
    const uid = document.getElementById(`${role}_uid`)?.value.trim();
    if (!name || !uid) { toast('請輸入姓名和 userId', 'error'); return; }
    try {
        await api('/api/contacts', 'POST', { user_id: uid, name, role });
        toast(`已新增${role === 'admin' ? '管理員' : '操作人員'}: ${name}`, 'success');
        setTimeout(() => location.reload(), 800);
    } catch (e) { toast(e.message, 'error'); }
}

async function removeContact(uid) {
    if (!confirm('確認移除？')) return;
    try {
        await api(`/api/contacts/${uid}`, 'DELETE');
        toast('已移除', 'success');
        setTimeout(() => location.reload(), 800);
    } catch (e) { toast(e.message, 'error'); }
}

// === 訊息操作 ===
async function genDraft(id) {
    toast('AI 生成中...', 'info');
    try {
        const data = await api(`/api/messages/${id}/draft`, 'POST');
        toast('草稿已生成', 'success');
        setTimeout(() => location.reload(), 800);
    } catch (e) { toast(e.message, 'error'); }
}

async function regenDraft(id) {
    return genDraft(id);
}

async function sendDraft(id) {
    if (!confirm('確認發送此回覆給客戶？')) return;
    try {
        await api(`/api/messages/${id}/send`, 'POST');
        toast('已發送', 'success');
        setTimeout(() => location.reload(), 800);
    } catch (e) { toast(e.message, 'error'); }
}

async function editDraft(id) {
    const draftEl = document.getElementById(`draft-${id}`);
    if (!draftEl) return;
    const original = draftEl.textContent;
    const newText = prompt('編輯回覆內容：', original);
    if (newText === null) return;
    try {
        await api(`/api/messages/${id}/send`, 'POST', { edited_text: newText });
        toast('已發送', 'success');
        setTimeout(() => location.reload(), 800);
    } catch (e) { toast(e.message, 'error'); }
}

async function markResolved(id) {
    try {
        await api(`/api/messages/${id}/resolve`, 'POST');
        toast('已標記為已處理', 'success');
        setTimeout(() => location.reload(), 800);
    } catch (e) { toast(e.message, 'error'); }
}

async function triggerPatrol() {
    toast('巡檢中...', 'info');
    try {
        await api('/api/patrol/trigger', 'POST');
        toast('巡檢完成', 'success');
        setTimeout(() => location.reload(), 1200);
    } catch (e) { toast(e.message, 'error'); }
}

// === 訊息日誌篩選 ===
document.addEventListener('DOMContentLoaded', () => {
    const dateFilter = document.getElementById('date-filter');
    const statusFilter = document.getElementById('status-filter');
    const searchInput = document.getElementById('search-input');

    function applyFilters() {
        const date = dateFilter?.value || '';
        const status = statusFilter?.value || '';
        const search = searchInput?.value.toLowerCase() || '';
        document.querySelectorAll('#message-list > div').forEach(row => {
            const matchesStatus = !status || row.dataset.status === status;
            const text = row.textContent.toLowerCase();
            const matchesSearch = !search || text.includes(search);
            row.style.display = (matchesStatus && matchesSearch) ? '' : 'none';
        });
    }

    dateFilter?.addEventListener('change', applyFilters);
    statusFilter?.addEventListener('change', applyFilters);
    searchInput?.addEventListener('input', applyFilters);
});
