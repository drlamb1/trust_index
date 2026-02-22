"""
EdgeFinder — Admin Panel HTML

Renders the admin panel page (user management).
Kept in a separate module to avoid bloating api/app.py.
"""

from __future__ import annotations


def admin_page_html(current_user_id: int, current_username: str) -> str:
    """Return the full admin panel HTML page."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>EdgeFinder — Admin</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg: #0b0e14; --surface: #12151e; --border: #1e2231;
      --text: #c9d1d9; --text-dim: #525b6b; --accent: #7c85f5;
      --up: #3fb950; --dn: #f85149;
    }}
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      background: var(--bg); color: var(--text);
      line-height: 1.6; -webkit-font-smoothing: antialiased;
    }}

    /* Topbar */
    .topbar {{
      display: flex; align-items: center; justify-content: space-between;
      padding: 14px 24px; background: var(--surface);
      border-bottom: 1px solid var(--border);
      position: sticky; top: 0; z-index: 10;
    }}
    .topbar-brand {{
      font-size: 13px; font-weight: 700; letter-spacing: 2.5px;
      text-transform: uppercase; color: var(--accent);
    }}
    .topbar-label {{
      font-size: 12px; color: var(--text-dim); font-weight: 400;
      margin-left: 16px; letter-spacing: 0.5px;
    }}
    .topbar-actions {{ display: flex; gap: 16px; align-items: center; }}
    .topbar-actions a {{
      font-size: 11px; color: var(--text-dim); text-decoration: none;
      text-transform: uppercase; letter-spacing: 1px; font-weight: 500;
      transition: color 0.15s;
    }}
    .topbar-actions a:hover {{ color: var(--accent); }}

    /* Layout */
    .container {{ max-width: 960px; margin: 0 auto; padding: 24px 20px 80px; }}

    /* Cards */
    .card {{
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 10px; padding: 20px 24px; margin-bottom: 16px;
    }}
    .card-title {{
      font-size: 12px; font-weight: 600; text-transform: uppercase;
      letter-spacing: 1.5px; color: var(--text-dim);
      margin-bottom: 16px; padding-bottom: 10px;
      border-bottom: 1px solid var(--border);
    }}

    /* Form elements */
    label {{
      display: block; font-size: 11px; font-weight: 600;
      text-transform: uppercase; letter-spacing: 1px;
      color: var(--text-dim); margin-bottom: 6px;
    }}
    input[type="email"], input[type="text"], input[type="password"], input[type="number"], select {{
      width: 100%; font-size: 14px; font-family: inherit;
      background: var(--bg); color: var(--text);
      border: 1px solid var(--border); border-radius: 8px;
      padding: 10px 12px; margin-bottom: 16px;
    }}
    input:focus, select:focus {{ outline: none; border-color: var(--accent); }}
    select {{ cursor: pointer; }}

    .form-row {{
      display: grid; grid-template-columns: 1fr 1fr; gap: 0 16px;
    }}
    .form-row.three {{ grid-template-columns: 1fr 1fr 1fr; }}

    .btn {{
      background: var(--accent); color: #fff; border: none; border-radius: 8px;
      padding: 10px 20px; font-size: 13px; font-weight: 600;
      cursor: pointer; transition: opacity 0.15s;
    }}
    .btn:hover {{ opacity: 0.85; }}
    .btn:disabled {{ opacity: 0.4; cursor: not-allowed; }}

    /* Table */
    .admin-table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    .admin-table th {{
      font-size: 11px; font-weight: 600; text-transform: uppercase;
      letter-spacing: 1px; color: var(--text-dim); text-align: left;
      padding: 8px 12px; border-bottom: 2px solid var(--border);
    }}
    .admin-table td {{
      padding: 10px 12px; border-bottom: 1px solid var(--border);
      vertical-align: middle;
    }}
    .admin-table tr:hover {{ background: rgba(124,133,245,0.04); }}
    .admin-table .mono {{
      font-family: 'JetBrains Mono', monospace; font-size: 12px;
    }}

    /* Role badges */
    .role-badge {{
      font-size: 10px; font-weight: 600; text-transform: uppercase;
      letter-spacing: 0.5px; padding: 3px 8px; border-radius: 4px;
      display: inline-block;
    }}
    .role-admin  {{ background: rgba(124,133,245,0.15); color: var(--accent); }}
    .role-member {{ background: rgba(210,153,34,0.15); color: #d29922; }}
    .role-viewer {{ background: var(--border); color: var(--text-dim); }}

    /* Status */
    .status-dot {{
      width: 8px; height: 8px; border-radius: 50%;
      display: inline-block; margin-right: 6px;
    }}
    .status-active   {{ background: var(--up); }}
    .status-inactive {{ background: var(--dn); }}

    /* Action buttons */
    .action-btn {{
      font-size: 11px; padding: 4px 10px; border-radius: 5px;
      border: 1px solid var(--border); background: none;
      color: var(--text-dim); cursor: pointer; transition: all 0.15s;
      font-family: inherit;
    }}
    .action-btn:hover {{ color: var(--accent); border-color: var(--accent); }}
    .action-btn.danger:hover {{ color: var(--dn); border-color: var(--dn); }}
    .actions-cell {{ display: flex; gap: 6px; flex-wrap: wrap; }}

    /* Modal */
    .modal-overlay {{
      position: fixed; inset: 0; z-index: 200;
      background: rgba(0,0,0,0.6);
      display: none; align-items: center; justify-content: center;
    }}
    .modal-overlay.open {{ display: flex; }}
    .modal-card {{
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 12px; padding: 32px; width: 420px; max-width: 90vw;
    }}
    .modal-title {{
      font-size: 14px; font-weight: 600; color: var(--text);
      margin-bottom: 20px;
    }}
    .modal-actions {{
      display: flex; gap: 10px; justify-content: flex-end; margin-top: 8px;
    }}
    .btn-secondary {{
      background: none; color: var(--text-dim); border: 1px solid var(--border);
      border-radius: 8px; padding: 10px 20px; font-size: 13px; font-weight: 500;
      cursor: pointer; transition: all 0.15s; font-family: inherit;
    }}
    .btn-secondary:hover {{ color: var(--text); border-color: var(--text-dim); }}

    /* Toast */
    .toast {{
      position: fixed; top: 20px; right: 20px; z-index: 300;
      padding: 12px 20px; border-radius: 8px; font-size: 13px;
      transition: opacity 0.3s; opacity: 0; pointer-events: none;
    }}
    .toast.show {{ opacity: 1; }}
    .toast-success {{ background: #0d2818; color: var(--up); border: 1px solid rgba(63,185,80,0.3); }}
    .toast-error   {{ background: #2a1215; color: var(--dn); border: 1px solid rgba(248,81,73,0.3); }}

    /* Empty state */
    .empty {{ text-align: center; color: var(--text-dim); padding: 32px; font-size: 14px; }}
    .you-badge {{
      font-size: 9px; color: var(--accent); border: 1px solid var(--accent);
      padding: 1px 5px; border-radius: 3px; margin-left: 6px;
      text-transform: uppercase; letter-spacing: 0.5px;
    }}
  </style>
</head>
<body>
  <nav class="topbar">
    <div>
      <span class="topbar-brand">EdgeFinder</span>
      <span class="topbar-label">Admin</span>
    </div>
    <div class="topbar-actions">
      <a href="/">dashboard</a>
      <span style="font-size:11px;color:var(--text-dim)">{current_username}</span>
      <a href="/logout">logout</a>
    </div>
  </nav>

  <main class="container">
    <!-- Create User -->
    <div class="card">
      <div class="card-title">Create User</div>
      <form id="createForm" onsubmit="createUser(event)">
        <div class="form-row">
          <div>
            <label for="newEmail">Email</label>
            <input type="email" id="newEmail" required>
          </div>
          <div>
            <label for="newUsername">Username</label>
            <input type="text" id="newUsername" required>
          </div>
        </div>
        <div class="form-row three">
          <div>
            <label for="newPassword">Password</label>
            <input type="password" id="newPassword" required minlength="8">
          </div>
          <div>
            <label for="newRole">Role</label>
            <select id="newRole" onchange="toggleBudget()">
              <option value="viewer">Viewer</option>
              <option value="member">Member</option>
              <option value="admin">Admin</option>
            </select>
          </div>
          <div id="budgetField">
            <label for="newBudget">Daily Token Budget</label>
            <input type="number" id="newBudget" value="50000" min="0">
          </div>
        </div>
        <button type="submit" class="btn">Create User</button>
      </form>
    </div>

    <!-- Users Table -->
    <div class="card">
      <div class="card-title">Users</div>
      <div id="usersTableWrap">
        <div class="empty">Loading...</div>
      </div>
    </div>
  </main>

  <!-- Edit User Modal -->
  <div class="modal-overlay" id="editModal">
    <div class="modal-card">
      <div class="modal-title">Edit User</div>
      <input type="hidden" id="editId">
      <div class="form-row">
        <div>
          <label for="editEmail">Email</label>
          <input type="email" id="editEmail">
        </div>
        <div>
          <label for="editUsername">Username</label>
          <input type="text" id="editUsername">
        </div>
      </div>
      <div class="form-row">
        <div>
          <label for="editRole">Role</label>
          <select id="editRole">
            <option value="viewer">Viewer</option>
            <option value="member">Member</option>
            <option value="admin">Admin</option>
          </select>
        </div>
        <div>
          <label for="editBudget">Daily Token Budget</label>
          <input type="number" id="editBudget" min="0">
        </div>
      </div>
      <div class="modal-actions">
        <button class="btn-secondary" onclick="closeModal()">Cancel</button>
        <button class="btn" onclick="saveEdit()">Save Changes</button>
      </div>
    </div>
  </div>

  <!-- Reset Password Modal -->
  <div class="modal-overlay" id="resetModal">
    <div class="modal-card">
      <div class="modal-title">Reset Password</div>
      <input type="hidden" id="resetId">
      <p style="font-size:13px;color:var(--text-dim);margin-bottom:16px" id="resetLabel"></p>
      <label for="resetPassword">New Password</label>
      <input type="password" id="resetPassword" minlength="8" placeholder="Minimum 8 characters">
      <div class="modal-actions">
        <button class="btn-secondary" onclick="closeResetModal()">Cancel</button>
        <button class="btn" onclick="saveResetPassword()">Reset Password</button>
      </div>
    </div>
  </div>

  <!-- Toast -->
  <div class="toast" id="toast"></div>

<script>
const CURRENT_USER_ID = {current_user_id};

// ── Toast ─────────────────────────────────────────────────────────────
function showToast(msg, type) {{
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast toast-' + type + ' show';
  setTimeout(() => t.classList.remove('show'), 3000);
}}

// ── Toggle budget field visibility ────────────────────────────────────
function toggleBudget() {{
  const role = document.getElementById('newRole').value;
  document.getElementById('budgetField').style.display = role === 'viewer' ? '' : 'none';
}}

// ── Load users ────────────────────────────────────────────────────────
async function loadUsers() {{
  try {{
    const res = await fetch('/api/auth/users');
    if (!res.ok) throw new Error('Failed to load users');
    const data = await res.json();
    renderTable(data.users);
  }} catch(e) {{
    document.getElementById('usersTableWrap').innerHTML =
      '<div class="empty">Failed to load users</div>';
  }}
}}

function renderTable(users) {{
  if (!users.length) {{
    document.getElementById('usersTableWrap').innerHTML =
      '<div class="empty">No users yet</div>';
    return;
  }}
  let html = `<table class="admin-table">
    <thead><tr>
      <th>User</th><th>Email</th><th>Role</th>
      <th>Status</th><th>Tokens</th><th>Actions</th>
    </tr></thead><tbody>`;

  for (const u of users) {{
    const isMe = u.id === CURRENT_USER_ID;
    const roleCls = 'role-' + u.role;
    const statusCls = u.is_active ? 'status-active' : 'status-inactive';
    const statusText = u.is_active ? 'Active' : 'Inactive';
    const youBadge = isMe ? '<span class="you-badge">you</span>' : '';
    const created = u.created_at ? new Date(u.created_at).toLocaleDateString() : '—';

    const toggleBtn = u.is_active
      ? `<button class="action-btn danger" onclick="toggleActive(${{u.id}},true)" ${{isMe?'disabled':''}}>Deactivate</button>`
      : `<button class="action-btn" onclick="toggleActive(${{u.id}},false)">Activate</button>`;

    html += `<tr>
      <td>${{u.username}}${{youBadge}}</td>
      <td style="color:var(--text-dim)">${{u.email}}</td>
      <td><span class="role-badge ${{roleCls}}">${{u.role}}</span></td>
      <td><span class="status-dot ${{statusCls}}"></span>${{statusText}}</td>
      <td class="mono">${{(u.tokens_used_today||0).toLocaleString()}}</td>
      <td class="actions-cell">
        <button class="action-btn" onclick='openEdit(${{JSON.stringify(u)}})'>Edit</button>
        <button class="action-btn" onclick="openResetPassword(${{u.id}},'${{u.username}}')">Password</button>
        ${{toggleBtn}}
        <button class="action-btn danger" onclick="deleteUser(${{u.id}},'${{u.username}}')" ${{isMe?'disabled':''}}>Delete</button>
      </td>
    </tr>`;
  }}

  html += '</tbody></table>';
  document.getElementById('usersTableWrap').innerHTML = html;
}}

// ── Create user ───────────────────────────────────────────────────────
async function createUser(e) {{
  e.preventDefault();
  const role = document.getElementById('newRole').value;
  const body = {{
    email: document.getElementById('newEmail').value,
    username: document.getElementById('newUsername').value,
    password: document.getElementById('newPassword').value,
    role: role,
    daily_token_budget: role === 'viewer' ? parseInt(document.getElementById('newBudget').value) : 0,
  }};
  try {{
    const res = await fetch('/api/admin/users', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify(body),
    }});
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Failed to create user');
    showToast('User created: ' + body.username, 'success');
    document.getElementById('createForm').reset();
    toggleBudget();
    loadUsers();
  }} catch(e) {{
    showToast(e.message, 'error');
  }}
}}

// ── Edit user modal ───────────────────────────────────────────────────
function openEdit(user) {{
  document.getElementById('editId').value = user.id;
  document.getElementById('editEmail').value = user.email;
  document.getElementById('editUsername').value = user.username;
  document.getElementById('editRole').value = user.role;
  document.getElementById('editBudget').value = user.daily_token_budget || 0;
  document.getElementById('editModal').classList.add('open');
}}

function closeModal() {{
  document.getElementById('editModal').classList.remove('open');
}}

async function saveEdit() {{
  const userId = document.getElementById('editId').value;
  const body = {{
    email: document.getElementById('editEmail').value,
    username: document.getElementById('editUsername').value,
    role: document.getElementById('editRole').value,
    daily_token_budget: parseInt(document.getElementById('editBudget').value),
  }};
  try {{
    const res = await fetch('/api/admin/users/' + userId, {{
      method: 'PATCH',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify(body),
    }});
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Failed to update user');
    showToast('User updated', 'success');
    closeModal();
    loadUsers();
  }} catch(e) {{
    showToast(e.message, 'error');
  }}
}}

// ── Reset password modal ──────────────────────────────────────────────
function openResetPassword(userId, username) {{
  document.getElementById('resetId').value = userId;
  document.getElementById('resetLabel').textContent = 'Set a new password for ' + username;
  document.getElementById('resetPassword').value = '';
  document.getElementById('resetModal').classList.add('open');
}}

function closeResetModal() {{
  document.getElementById('resetModal').classList.remove('open');
}}

async function saveResetPassword() {{
  const userId = document.getElementById('resetId').value;
  const pw = document.getElementById('resetPassword').value;
  if (pw.length < 8) {{ showToast('Password must be at least 8 characters', 'error'); return; }}
  try {{
    const res = await fetch('/api/admin/users/' + userId + '/reset-password', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{ new_password: pw }}),
    }});
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Failed to reset password');
    showToast('Password reset', 'success');
    closeResetModal();
  }} catch(e) {{
    showToast(e.message, 'error');
  }}
}}

// ── Toggle active ─────────────────────────────────────────────────────
async function toggleActive(userId, currentlyActive) {{
  const action = currentlyActive ? 'deactivate' : 'activate';
  try {{
    const res = await fetch('/api/admin/users/' + userId + '/' + action, {{ method: 'POST' }});
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Failed');
    showToast('User ' + action + 'd', 'success');
    loadUsers();
  }} catch(e) {{
    showToast(e.message, 'error');
  }}
}}

// ── Delete user ───────────────────────────────────────────────────────
async function deleteUser(userId, username) {{
  if (!confirm('Delete user "' + username + '"? This cannot be undone.')) return;
  try {{
    const res = await fetch('/api/admin/users/' + userId, {{ method: 'DELETE' }});
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Failed to delete');
    showToast('User deleted: ' + username, 'success');
    loadUsers();
  }} catch(e) {{
    showToast(e.message, 'error');
  }}
}}

// ── Close modals on backdrop click ────────────────────────────────────
document.querySelectorAll('.modal-overlay').forEach(m => {{
  m.addEventListener('click', e => {{
    if (e.target === m) m.classList.remove('open');
  }});
}});

// ── Init ──────────────────────────────────────────────────────────────
toggleBudget();
loadUsers();
</script>
</body>
</html>"""
