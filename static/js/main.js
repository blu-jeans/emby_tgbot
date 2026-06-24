document.addEventListener('DOMContentLoaded', () => {
    // 轮询 Bot 状态
    checkBotStatus();
    setInterval(checkBotStatus, 5000);

    // 初始化白名单群组标签输入
    initTagsInput();

    // 绑定设置表单提交
    const settingsForm = document.getElementById('settingsForm');
    if (settingsForm) {
        settingsForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData(settingsForm);
            const data = {};
            formData.forEach((value, key) => {
                data[key] = value;
            });

            try {
                const response = await fetch('/api/settings', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(data),
                });
                const result = await response.json();
                if (response.ok) {
                    showToast('系统设置已成功保存！', 'success');
                    // 延迟刷新以确认 Bot 状态是否有更新
                    setTimeout(checkBotStatus, 1500);
                } else {
                    showToast(result.error || '保存设置失败，请重试', 'error');
                }
            } catch (err) {
                showToast('网络请求发生异常', 'error');
            }
        });
    }

    // 绑定修改密码表单提交
    const passwordForm = document.getElementById('passwordForm');
    if (passwordForm) {
        passwordForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const oldPassword = document.getElementById('oldPassword').value;
            const newPassword = document.getElementById('newPassword').value;
            const confirmPassword = document.getElementById('confirmPassword').value;

            if (newPassword !== confirmPassword) {
                showToast('两次输入的新密码不一致！', 'error');
                return;
            }

            try {
                const response = await fetch('/api/password', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ oldPassword, newPassword }),
                });
                const result = await response.json();
                if (response.ok) {
                    showToast('管理员密码修改成功！', 'success');
                    passwordForm.reset();
                } else {
                    showToast(result.error || '修改密码失败', 'error');
                }
            } catch (err) {
                showToast('网络请求发生异常', 'error');
            }
        });
    }
});

// 检查并更新 Bot 状态指示器
async function checkBotStatus() {
    const statusText = document.getElementById('statusText');
    const statusContainer = document.getElementById('statusContainer');
    if (!statusText || !statusContainer) return;

    try {
        const response = await fetch('/api/status');
        const data = await response.json();
        
        statusContainer.className = 'bot-status';
        if (data.status === 'running') {
            statusContainer.classList.add('status-active');
            statusText.innerText = '运行中';
        } else if (data.status === 'stopped') {
            statusContainer.classList.add('status-inactive');
            statusText.innerText = '已停止 (未配置 Token)';
        } else if (data.status === 'error') {
            statusContainer.classList.add('status-inactive');
            statusText.innerText = '运行出错';
        } else {
            statusContainer.classList.add('status-loading');
            statusText.innerText = '初始化中';
        }
    } catch (err) {
        statusContainer.className = 'bot-status status-inactive';
        statusText.innerText = '连接中断';
    }
}

// 切换显示已注册用户的密码明文/密文
function togglePassword(btn, userId) {
    const pwdText = document.getElementById(`pwd-${userId}`);
    if (!pwdText) return;
    
    if (pwdText.classList.contains('masked')) {
        pwdText.classList.remove('masked');
        btn.innerHTML = '👁️';
    } else {
        pwdText.classList.add('masked');
        btn.innerHTML = '🙈';
    }
}

// 删除已创建的用户
async function deleteUser(userId, username) {
    if (!confirm(`您确定要从数据库中删除用户 "${username}" 吗？此操作仅删除登记记录，Emby 服务器上的账号需手动清理。`)) {
        return;
    }

    try {
        const response = await fetch(`/api/users/delete/${userId}`, {
            method: 'POST',
        });
        const result = await response.json();
        if (response.ok) {
            showToast(`用户 "${username}" 记录已成功删除！`, 'success');
            // 从 DOM 中移除这一行
            const row = document.getElementById(`user-row-${userId}`);
            if (row) row.remove();
            
            // 检查如果表格空了，提示无数据
            const tbody = document.querySelector('table tbody');
            if (tbody && tbody.children.length === 0) {
                tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-muted);">暂无注册用户数据</td></tr>';
            }
        } else {
            showToast(result.error || '删除记录失败', 'error');
        }
    } catch (err) {
        showToast('网络请求错误', 'error');
    }
}

// 简易 Toast 通知组件
function showToast(message, type = 'success') {
    // 检查是否存在 toast-container，没有则创建
    let container = document.querySelector('.toast-container');
    if (!container) {
        container = document.createElement('div');
        container.className = 'toast-container';
        document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    
    let icon = 'ℹ️';
    if (type === 'success') icon = '✅';
    if (type === 'error') icon = '❌';
    
    toast.innerHTML = `<span>${icon}</span> <span>${message}</span>`;
    container.appendChild(toast);

    // 触发浮现动画
    setTimeout(() => {
        toast.classList.add('show');
    }, 10);

    // 3秒后淡出删除
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => {
            toast.remove();
        }, 300);
    }, 3000);
}

// 初始化标签化输入框组件 (允许输入多个群组 ID)
function initTagsInput() {
    const container = document.getElementById('tagsInputContainer');
    const list = document.getElementById('tagsList');
    const input = document.getElementById('tagInput');
    const hiddenInput = document.getElementById('allowed_chat_id');
    
    if (!container || !list || !input || !hiddenInput) return;
    
    let tags = [];
    
    // 初始化渲染已配置的标签
    const initialVal = hiddenInput.value.trim();
    if (initialVal) {
        tags = initialVal.split(',').map(x => x.trim()).filter(x => x);
        renderTags();
    }
    
    // 点击容器主体聚焦到输入框
    container.addEventListener('click', (e) => {
        if (e.target !== input && !e.target.classList.contains('tag-pill-remove')) {
            input.focus();
        }
    });
    
    // 监听输入框的回车和逗号
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ',') {
            e.preventDefault();
            const val = input.value.trim().replace(',', '');
            if (val) {
                addTag(val);
            }
        }
    });
    
    // 失去焦点时自动添加已输入的 ID
    input.addEventListener('blur', () => {
        const val = input.value.trim();
        if (val) {
            addTag(val);
        }
    });
    
    function addTag(val) {
        // 校验群组 ID 格式 (允许带负号的整型数字)
        const idPattern = /^-?\d+$/;
        if (!idPattern.test(val)) {
            showToast('Telegram 群组 ID 格式不正确，必须为数字！', 'error');
            input.value = '';
            return;
        }
        
        if (tags.includes(val)) {
            showToast('该群组 ID 已经在列表中了', 'error');
            input.value = '';
            return;
        }
        
        tags.push(val);
        input.value = '';
        updateHiddenValue();
        renderTags();
    }
    
    // 挂载到 window 作用域以便 onclick 属性调用
    window.removeTag = function(index) {
        tags.splice(index, 1);
        updateHiddenValue();
        renderTags();
    }
    
    function renderTags() {
        list.innerHTML = '';
        tags.forEach((tag, idx) => {
            const pill = document.createElement('div');
            pill.className = 'tag-pill';
            pill.innerHTML = `
                <span>${tag}</span>
                <button type="button" class="tag-pill-remove" onclick="removeTag(${idx})">×</button>
            `;
            list.appendChild(pill);
        });
    }
    
    function updateHiddenValue() {
        hiddenInput.value = tags.join(',');
    }
}

