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
    const payload = {
        line: {
            channel_access_token: document.getElementById('line_token')?.value || '',
            webhook_url: document.getElementById('webhook_url')?.value || ''
        },
        notification: {
            first_reminder_hours: parseInt(document.getElementById('reminder_1')?.value || 1),
            second_reminder_hours: parseInt(document.getElementById('reminder_2')?.value || 3),
            escalation_hours: parseInt(document.getElementById('reminder_3')?.value || 6),
            patrol_interval_minutes: parseInt(document.getElementById('patrol_interval')?.value || 15),
            suppression_enabled: document.getElementById('suppress_enabled')?.checked ?? true
        },
        ai: {
            model: document.getElementById('ai_model')?.value || 'default',
            company_info: document.getElementById('company_info')?.value || '',
            auto_send: document.getElementById('auto_send')?.checked ?? false
        },
        rag: {
            enabled: document.getElementById('rag_enabled')?.checked ?? false,
            kb_path: document.getElementById('kb_path')?.value || '',
            top_k: parseInt(document.getElementById('rag_top_k')?.value || 3)
        },
        notify_channels: {
            line: { enabled: document.getElementById('ch_line_enabled')?.checked ?? true },
            discord: {
                enabled: document.getElementById('ch_discord_enabled')?.checked ?? false,
                webhook_url: document.getElementById('discord_webhook')?.value || ''
            },
            telegram: {
                enabled: document.getElementById('ch_telegram_enabled')?.checked ?? false,
                bot_token: document.getElementById('telegram_token')?.value || '',
                chat_id: document.getElementById('telegram_chat_id')?.value || ''
            },
            email: {
                enabled: document.getElementById('ch_email_enabled')?.checked ?? false,
                smtp_host: document.getElementById('smtp_host')?.value || '',
                smtp_port: parseInt(document.getElementById('smtp_port')?.value || 465),
                smtp_user: document.getElementById('smtp_user')?.value || '',
                smtp_password: document.getElementById('smtp_password')?.value || '',
                use_tls: document.getElementById('smtp_tls')?.checked ?? true,
                from_email: document.getElementById('smtp_from')?.value || '',
                to_emails: (document.getElementById('smtp_to')?.value || '').split(',').map(s => s.trim()).filter(Boolean)
            }
        },
        heartbeat: {
            enabled: document.getElementById('hb_enabled')?.checked ?? true,
            max_stale_minutes: parseInt(document.getElementById('hb_max_stale')?.value || 60)
        }
    };
    try {
        await api('/api/settings', 'POST', payload);
        toast('設定已儲存', 'success');
    } catch (e) { toast(e.message, 'error'); }
}

async function testChannel(channel) {
    try {
        const data = await api('/api/notify/test', 'POST', { channel });
        toast(data.success ? `✅ ${channel} 連線成功` : `❌ ${channel}: ${data.message}`, data.success ? 'success' : 'error');
    } catch (e) { toast(e.message, 'error'); }
}

async function testRag() {
    const q = document.getElementById('rag_test_q')?.value;
    if (!q) { toast('請輸入測試問題', 'error'); return; }
    try {
        const r = await fetch(`/api/rag/search?q=${encodeURIComponent(q)}`);
        const data = await r.json();
        const el = document.getElementById('rag-test-result');
        el.innerHTML = '';
        el.classList.remove('hidden');
        if (!data.success) {
            el.innerHTML = `<div class="text-red-600">${data.message}</div>`;
            return;
        }
        if (!data.results.length) {
            el.innerHTML = `<div class="text-gray-500">無相符知識庫內容</div>`;
            return;
        }
        data.results.forEach(res => {
            el.innerHTML += `<div class="border rounded p-2 mb-1"><b>${res.source}</b> <span class="text-xs text-gray-400">分數 ${res.score}</span><div class="text-xs text-gray-600 mt-1">${res.snippet.slice(0, 200)}...</div></div>`;
        });
        toast(`檢索到 ${data.results.length} 筆`, 'success');
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
