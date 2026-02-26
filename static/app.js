/* ═══════════════════════════════════════════
   LLM → SCORM → Chamilo — Frontend Logic
   ═══════════════════════════════════════════ */

// ─── State ───
let lastCourse = null;
let lastScormFilename = null;

// ─── Init ───
document.addEventListener('DOMContentLoaded', () => {
    loadSettings();
    loadHistory();

    // Drag & drop for JSON
    const drop = document.getElementById('file-drop');
    if (drop) {
        drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('active'); });
        drop.addEventListener('dragleave', () => drop.classList.remove('active'));
        drop.addEventListener('drop', e => {
            e.preventDefault();
            drop.classList.remove('active');
            const file = e.dataTransfer.files[0];
            if (file) handleJSONFile(file);
        });
    }
});

// ─── API Helper ───
async function api(url, data = null) {
    const opts = { headers: { 'Content-Type': 'application/json' } };
    if (data) {
        opts.method = 'POST';
        opts.body = JSON.stringify(data);
    }
    const resp = await fetch(url, opts);
    return resp.json();
}

// ═══════════════════════════════════════════
//  Settings
// ═══════════════════════════════════════════

async function loadSettings() {
    try {
        const s = await api('/api/settings');
        document.getElementById('chamilo-url').value = s.chamilo_url || '';
        document.getElementById('chamilo-user').value = s.chamilo_user || 'admin';
        document.getElementById('chamilo-pass').value = s.chamilo_password === '••••' ? '' : '';
        document.getElementById('llm-url').value = s.llm_base_url || '';
        document.getElementById('llm-model').value = s.llm_model || '';

        if (s.llm_api_key && s.llm_api_key !== '') {
            document.querySelector('input[name="llm-type"][value="api"]').checked = true;
            toggleLLMType();
        }

        // Auto-test connections if settings exist
        if (s.chamilo_url) setTimeout(testChamilo, 500);
        if (s.llm_base_url) setTimeout(testLLM, 800);
    } catch (e) { /* ignore */ }
}

async function saveSettings() {
    const data = getSettings();
    setStatus('chamilo-status', 'loading');
    await api('/api/settings', data);
    setStatus('chamilo-status', '');
    showMsg('action-msg', 'Настройки сохранены', 'ok');
    setTimeout(() => hideMsg('action-msg'), 2000);
}

function getSettings() {
    const isLocal = document.querySelector('input[name="llm-type"]:checked').value === 'local';
    return {
        chamilo_url: document.getElementById('chamilo-url').value.trim(),
        chamilo_user: document.getElementById('chamilo-user').value.trim() || 'admin',
        chamilo_password: document.getElementById('chamilo-pass').value.trim(),
        llm_base_url: isLocal ? document.getElementById('llm-url').value.trim() : '',
        llm_model: isLocal ? document.getElementById('llm-model').value.trim() : document.getElementById('llm-model-api').value.trim(),
        llm_api_key: !isLocal ? document.getElementById('llm-apikey').value.trim() : '',
    };
}

// ═══════════════════════════════════════════
//  Connection Tests
// ═══════════════════════════════════════════

async function testChamilo() {
    setStatus('chamilo-status', 'loading');
    setBtnLoading('chamilo-btn-text', true);
    hideMsg('chamilo-msg');

    try {
        const result = await api('/api/test-chamilo', {
            url: document.getElementById('chamilo-url').value.trim(),
            user: document.getElementById('chamilo-user').value.trim() || 'admin',
            password: document.getElementById('chamilo-pass').value.trim(),
        });

        if (result.ok) {
            setStatus('chamilo-status', 'ok');
            showMsg('chamilo-msg', 'Connected: ' + result.message, 'ok');
            loadChamiloCourses();
        } else {
            setStatus('chamilo-status', 'fail');
            showMsg('chamilo-msg', 'Error: ' + result.error, 'fail');
        }
    } catch (e) {
        setStatus('chamilo-status', 'fail');
        showMsg('chamilo-msg', 'Connection failed', 'fail');
    }

    setBtnLoading('chamilo-btn-text', false, 'Проверить');
}

async function testLLM() {
    setStatus('llm-status', 'loading');
    setBtnLoading('llm-btn-text', true);
    hideMsg('llm-msg');

    const isLocal = document.querySelector('input[name="llm-type"]:checked').value === 'local';

    try {
        const result = await api('/api/test-llm', {
            base_url: isLocal ? document.getElementById('llm-url').value.trim() : '',
            model: isLocal ? document.getElementById('llm-model').value.trim() : document.getElementById('llm-model-api').value.trim(),
            api_key: !isLocal ? document.getElementById('llm-apikey').value.trim() : '',
        });

        if (result.ok) {
            setStatus('llm-status', 'ok');
            showMsg('llm-msg', 'Connected: ' + result.message, 'ok');
        } else {
            setStatus('llm-status', 'fail');
            showMsg('llm-msg', 'Error: ' + result.error, 'fail');
        }
    } catch (e) {
        setStatus('llm-status', 'fail');
        showMsg('llm-msg', 'Connection failed', 'fail');
    }

    setBtnLoading('llm-btn-text', false, 'Проверить');
}

async function loadChamiloCourses() {
    const select = document.getElementById('chamilo-course-select');
    const result = await api('/api/chamilo-courses', {
        url: document.getElementById('chamilo-url').value.trim(),
        user: document.getElementById('chamilo-user').value.trim() || 'admin',
        password: document.getElementById('chamilo-pass').value.trim(),
    });

    select.innerHTML = '<option value="">Выберите курс Chamilo...</option>';
    if (result.ok && result.courses.length > 0) {
        result.courses.forEach(c => {
            const opt = document.createElement('option');
            opt.value = c;
            opt.textContent = c;
            select.appendChild(opt);
        });
        select.value = result.courses[0];
    }
}

// ═══════════════════════════════════════════
//  Course Generation
// ═══════════════════════════════════════════

async function generateCourse() {
    const topic = document.getElementById('topic').value.trim();
    if (!topic) {
        document.getElementById('topic').focus();
        return;
    }

    const btn = document.getElementById('btn-generate');
    btn.disabled = true;
    btn.innerHTML = 'Генерация...';

    showProgress('Генерация курса через ИИ... Это может занять несколько минут.');
    setProgressStep('gen');

    const settings = getSettings();

    try {
        const result = await api('/api/generate', {
            topic,
            num_modules: parseInt(document.getElementById('numModules').value) || 1,
            sections_per_module: parseInt(document.getElementById('sectionsPerModule').value) || 1,
            scos_per_section: parseInt(document.getElementById('scosPerSection').value) || 1,
            screens_per_sco: parseInt(document.getElementById('screensPerSco').value) || 2,
            questions_per_sco: parseInt(document.getElementById('questionsPerSco').value) || 1,
            final_test_questions: parseInt(document.getElementById('finalTestQuestions').value) || 3,
            lang: document.getElementById('lang').value,
            base_url: settings.llm_base_url,
            model: settings.llm_model,
            api_key: settings.llm_api_key,
            temperature: parseFloat(document.getElementById('temperature').value),
            max_tokens: parseInt(document.getElementById('max-tokens').value),
            detail_level: document.getElementById('detailLevel').value,
            system_prompt: document.getElementById('system-prompt').value.trim(),
            extra_instructions: document.getElementById('extra-instructions').value.trim(),
        });

        if (result.ok) {
            pollGeneration();
        } else {
            hideProgress();
            showMsg('action-msg', 'Error: ' + result.error, 'fail');
            btn.disabled = false;
            btn.innerHTML = '🤖 Сгенерировать';
        }
    } catch (e) {
        hideProgress();
        showMsg('action-msg', 'Network error', 'fail');
        btn.disabled = false;
        btn.innerHTML = '🤖 Сгенерировать';
    }
}

function pollGeneration() {
    if (window._genInterval) clearInterval(window._genInterval);
    if (window._progressInterval) clearInterval(window._progressInterval); // stop fake bar

    window._genInterval = setInterval(async () => {
        try {
            const res = await api('/api/generate-status');
            if (res.ok) {
                if (res.msg) updateProgressText(res.msg);
                if (res.pct !== undefined) {
                    const bar = document.getElementById('gen-progress');
                    bar.style.width = res.pct + '%';
                }

                if (!res.generating) {
                    clearInterval(window._genInterval);
                    const btn = document.getElementById('btn-generate');

                    if (res.course) {
                        lastCourse = res.course;
                        renderPreview(res.course);
                        populateJSONEditor(res.course);

                        setProgressStep('build');
                        updateProgressText('Сборка SCORM-пакета...');
                        await buildSCORM();
                        setProgressStep('done');
                        updateProgressText('Готово!');
                        setTimeout(hideProgress, 2000);
                        loadHistory();
                    } else if (res.error) {
                        hideProgress();
                        showMsg('action-msg', 'Error: ' + res.error, 'fail');
                    } else {
                        hideProgress();
                    }

                    btn.disabled = false;
                    btn.innerHTML = '🤖 Сгенерировать';
                }
            }
        } catch (e) {
            console.error("Poll error", e);
        }
    }, 1500);
}

function loadJSON(input) {
    const file = input.files[0];
    if (file) handleJSONFile(file);
}

function handleJSONFile(file) {
    const reader = new FileReader();
    reader.onload = async (e) => {
        try {
            const course = JSON.parse(e.target.result);
            document.getElementById('file-drop').innerHTML = 'Loaded: ' + file.name;
            document.getElementById('file-drop').classList.add('active');

            lastCourse = course;
            await api('/api/generate-from-json', { course });
            renderPreview(course);
            populateJSONEditor(course);
            await buildSCORM();
            loadHistory();
        } catch (err) {
            document.getElementById('file-drop').innerHTML = 'JSON Error: ' + err.message;
        }
    };
    reader.readAsText(file);
}

// ═══════════════════════════════════════════
//  Preview — Overview Tab
// ═══════════════════════════════════════════

function renderPreview(course) {
    const section = document.getElementById('preview-section');
    section.style.display = '';

    loadChamiloCourses();

    let totalModules = 0, totalSections = 0, totalScos = 0, totalScreens = 0, totalQuizzes = 0;
    let html = '';

    if (course.modules) {
        totalModules = course.modules.length;
        course.modules.forEach((mod, mi) => {
            html += `<div class="page-card open" style="margin-bottom:10px">
                <div class="page-card-header" style="background:var(--bg-light)">
                    <strong>Модуль ${mi + 1}:</strong> ${mod.title}
                </div>
                <div class="page-card-body">`;

            const sections = mod.sections || [];
            totalSections += sections.length;

            sections.forEach((sec, si) => {
                html += `<div style="margin-left: 15px; border-left: 2px solid var(--border); padding-left: 10px; margin-bottom: 10px;">
                    <strong>Раздел ${si + 1}:</strong> ${sec.title}`;

                const scos = sec.scos || [];
                totalScos += scos.length;

                scos.forEach((sco, sci) => {
                    html += `<div style="margin-top: 10px;"><em>SCO ${sci + 1}:</em> ${sco.title}`;
                    const screens = sco.screens || [];
                    totalScreens += screens.length;

                    html += `<ul style="font-size: 0.9em; color: var(--text-secondary); margin-top: 5px;">`;
                    screens.forEach(scr => {
                        html += `<li>📄 ${scr.title} (${scr.blocks ? scr.blocks.length : 0} блоков)</li>`;
                    });

                    if (sco.knowledge_check) {
                        totalQuizzes += sco.knowledge_check.length;
                        html += `<li>❓ Проверка знаний (${sco.knowledge_check.length} вопросов)</li>`;
                    }
                    html += `</ul></div>`;
                });

                html += `</div>`;
            });
            html += `</div></div>`;
        });

        if (course.final_test) {
            totalQuizzes += course.final_test.length;
            html += `<div class="page-card open" style="margin-bottom:10px">
                <div class="page-card-header" style="background:var(--bg-light)">
                    <strong>Итоговый тест</strong>
                </div>
                <div class="page-card-body">
                    <ul><li>❓ ${course.final_test.length} вопросов</li></ul>
                </div>
            </div>`;
        }
    } else {
        // Fallback for flat structure
        const pages = course.pages || [];
        totalScreens = pages.length;
        html += `<div class="page-card open"><div class="page-card-header">Плоская структура (${pages.length} стр.)</div></div>`;
    }

    document.getElementById('course-header').innerHTML = `
        <div class="course-title">${course.title || 'Без названия'}</div>
        <div class="course-desc">${course.description || ''}</div>
        <div class="course-stats" style="margin-top: 10px; flex-wrap: wrap; gap: 10px;">
            <div class="stat">📦 <span>${totalModules}</span> модулей</div>
            <div class="stat">📑 <span>${totalScos}</span> SCO</div>
            <div class="stat">📄 <span>${totalScreens}</span> экранов</div>
            <div class="stat">❓ <span>${totalQuizzes}</span> вопросов</div>
        </div>
    `;

    document.getElementById('course-pages').innerHTML = html;
    section.scrollIntoView({ behavior: 'smooth' });
}

// ═══════════════════════════════════════════
//  Preview Tabs
// ═══════════════════════════════════════════

function switchPreviewTab(tab) {
    ['overview', 'live', 'json'].forEach(t => {
        const pane = document.getElementById('pane-' + t);
        const ptab = document.getElementById('ptab-' + t);
        if (pane) pane.style.display = (t === tab) ? '' : 'none';
        if (ptab) ptab.classList.toggle('active', t === tab);
    });

    // Load iframe when switching to live tab
    if (tab === 'live') {
        refreshPreview();
    }
}

function refreshPreview() {
    const iframe = document.getElementById('scorm-preview-iframe');
    if (iframe) {
        iframe.src = '/api/preview-scorm?t=' + Date.now();
    }
}

function openPreviewFullscreen() {
    window.open('/api/preview-scorm', '_blank');
}

// ═══════════════════════════════════════════
//  JSON Editor
// ═══════════════════════════════════════════

function populateJSONEditor(course) {
    const editor = document.getElementById('json-editor');
    if (editor) {
        editor.value = JSON.stringify(course, null, 2);
        validateJSONInput();
    }
}

function validateJSONInput() {
    const editor = document.getElementById('json-editor');
    const status = document.getElementById('json-status');
    const errorEl = document.getElementById('json-error');
    const btnSave = document.getElementById('btn-save-json');

    try {
        JSON.parse(editor.value);
        status.textContent = 'Valid JSON';
        status.className = 'json-status valid';
        errorEl.style.display = 'none';
        if (btnSave) btnSave.disabled = false;
    } catch (e) {
        status.textContent = 'Invalid JSON';
        status.className = 'json-status invalid';
        errorEl.textContent = e.message;
        errorEl.style.display = 'block';
        if (btnSave) btnSave.disabled = true;
    }
}

function formatJSON() {
    const editor = document.getElementById('json-editor');
    try {
        const obj = JSON.parse(editor.value);
        editor.value = JSON.stringify(obj, null, 2);
        validateJSONInput();
    } catch (e) {
        // Can't format invalid JSON
    }
}

async function saveJSON() {
    const editor = document.getElementById('json-editor');
    const btn = document.getElementById('btn-save-json');

    try {
        const course = JSON.parse(editor.value);
        btn.disabled = true;
        btn.textContent = 'Saving...';

        const result = await api('/api/update-course', { course });

        if (result.ok) {
            lastCourse = result.course;
            lastScormFilename = result.filename;
            renderPreview(result.course);
            showMsg('action-msg', 'JSON saved, SCORM rebuilt: ' + result.filename, 'ok');
            loadHistory();
        } else {
            showMsg('action-msg', 'Validation error: ' + result.error, 'fail');
        }
    } catch (e) {
        showMsg('action-msg', 'JSON parse error: ' + e.message, 'fail');
    }

    btn.disabled = false;
    btn.textContent = '💾 Сохранить и пересобрать';
}

// ═══════════════════════════════════════════
//  History
// ═══════════════════════════════════════════

async function loadHistory() {
    try {
        const result = await api('/api/history');
        const list = document.getElementById('history-list');

        if (!result.ok || result.items.length === 0) {
            list.innerHTML = '<div class="history-empty">Пока нет сгенерированных пакетов</div>';
            return;
        }

        list.innerHTML = result.items.map(item => {
            const date = new Date(item.created * 1000);
            const dateStr = date.toLocaleDateString('ru-RU') + ' ' + date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
            return `
                <div class="history-item">
                    <div class="history-info">
                        <span class="history-name">${item.filename}</span>
                        <span class="history-meta">${dateStr} &middot; ${item.size_kb} KB</span>
                    </div>
                    <a href="/api/download/${item.filename}" class="btn btn-sm btn-secondary history-download" download>
                        💾
                    </a>
                </div>
            `;
        }).join('');
    } catch (e) {
        // Ignore
    }
}

function toggleHistory() {
    const body = document.getElementById('history-body');
    const chevron = document.getElementById('history-chevron');
    const isHidden = body.style.display === 'none';
    body.style.display = isHidden ? '' : 'none';
    chevron.textContent = isHidden ? '▴' : '▾';
}

// ═══════════════════════════════════════════
//  SCORM Build & Upload
// ═══════════════════════════════════════════

async function buildSCORM() {
    try {
        const result = await api('/api/build-scorm', {});
        if (result.ok) {
            lastScormFilename = result.filename;
            showMsg('action-msg', 'SCORM created: ' + result.filename, 'ok');
        } else {
            showMsg('action-msg', 'Error: ' + result.error, 'fail');
        }
    } catch (e) {
        showMsg('action-msg', 'Build error', 'fail');
    }
}

function downloadSCORM() {
    if (lastScormFilename) {
        window.open('/api/download/' + lastScormFilename, '_blank');
    } else {
        showMsg('action-msg', 'Generate a course first', 'fail');
    }
}

async function uploadToChamilo() {
    const selectVal = document.getElementById('chamilo-course-select').value;
    const manualVal = document.getElementById('chamilo-course-manual').value.trim();
    const courseCode = manualVal || selectVal;

    if (!courseCode) {
        showMsg('action-msg', 'Select or enter a Chamilo course code', 'fail');
        return;
    }

    const btn = document.getElementById('btn-upload');
    btn.disabled = true;
    btn.innerHTML = 'Uploading...';

    try {
        const result = await api('/api/upload', {
            course_code: courseCode,
            chamilo_url: document.getElementById('chamilo-url').value.trim(),
            chamilo_user: document.getElementById('chamilo-user').value.trim() || 'admin',
            chamilo_password: document.getElementById('chamilo-pass').value.trim(),
        });

        if (result.ok) {
            showMsg('action-msg', result.message, 'ok');
        } else {
            showMsg('action-msg', 'Error: ' + result.error, 'fail');
        }
    } catch (e) {
        showMsg('action-msg', 'Upload error', 'fail');
    }

    btn.disabled = false;
    btn.innerHTML = '📤 Загрузить в Chamilo';
}

// ═══════════════════════════════════════════
//  UI Helpers
// ═══════════════════════════════════════════

function togglePanel(id) {
    const el = document.getElementById(id);
    if (el) el.classList.toggle('collapsed');
}

function toggleLLMType() {
    const isLocal = document.querySelector('input[name="llm-type"]:checked').value === 'local';
    document.getElementById('llm-local-fields').style.display = isLocal ? '' : 'none';
    document.getElementById('llm-api-fields').style.display = isLocal ? 'none' : '';
}

function switchTab(tab) {
    document.getElementById('tab-ai').classList.toggle('active', tab === 'ai');
    document.getElementById('tab-json').classList.toggle('active', tab === 'json');
    document.getElementById('form-ai').style.display = tab === 'ai' ? '' : 'none';
    document.getElementById('form-json').style.display = tab === 'json' ? '' : 'none';
}

function onCourseSelect() {
    const val = document.getElementById('chamilo-course-select').value;
    if (val) {
        document.getElementById('chamilo-course-manual').value = '';
    }
}

function setStatus(id, status) {
    const el = document.getElementById(id);
    el.className = 'status-dot' + (status ? ' ' + status : '');
}

function showMsg(id, msg, type) {
    const el = document.getElementById(id);
    el.textContent = msg;
    el.className = 'status-msg show ' + type;
}

function hideMsg(id) {
    const el = document.getElementById(id);
    el.className = 'status-msg';
}

function setBtnLoading(id, loading, text) {
    const el = document.getElementById(id);
    if (loading) {
        el.textContent = '...';
    } else {
        el.textContent = text || 'Проверить';
    }
}

// ═══════════════════════════════════════════
//  Progress Bar (improved)
// ═══════════════════════════════════════════

function showProgress(text) {
    const section = document.getElementById('progress-section');
    section.style.display = '';
    document.getElementById('progress-text').textContent = text;

    // Reset steps
    ['step-gen', 'step-build', 'step-done'].forEach(id => {
        const el = document.getElementById(id);
        el.className = 'progress-step';
    });
    document.getElementById('step-gen').classList.add('active');

    // Animate progress
    const bar = document.getElementById('gen-progress');
    bar.style.width = '10%';
    let w = 10;
    window._progressInterval = setInterval(() => {
        w = Math.min(w + Math.random() * 5, 90);
        bar.style.width = w + '%';
    }, 2000);
}

function setProgressStep(step) {
    const steps = ['gen', 'build', 'done'];
    const idx = steps.indexOf(step);
    steps.forEach((s, i) => {
        const el = document.getElementById('step-' + s);
        el.className = 'progress-step';
        if (i < idx) el.classList.add('completed');
        if (i === idx) el.classList.add('active');
    });

    // Update bar
    const bar = document.getElementById('gen-progress');
    const pcts = { gen: 30, build: 70, done: 100 };
    bar.style.width = (pcts[step] || 50) + '%';
}

function updateProgressText(text) {
    document.getElementById('progress-text').textContent = text;
}

function hideProgress() {
    clearInterval(window._progressInterval);
    const bar = document.getElementById('gen-progress');
    bar.style.width = '100%';
    setTimeout(() => {
        document.getElementById('progress-section').style.display = 'none';
        bar.style.width = '0%';
    }, 500);
}
