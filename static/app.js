/* ═══════════════════════════════════════════
   LLM → SCORM → Chamilo — Frontend Logic
   ═══════════════════════════════════════════ */

// ─── State ───
let lastCourse = null;
let lastScormFilename = null;

// ─── Init ───
document.addEventListener('DOMContentLoaded', () => {
    loadSettings();

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
            showMsg('chamilo-msg', '✅ ' + result.message, 'ok');
            loadChamiloCourses();
        } else {
            setStatus('chamilo-status', 'fail');
            showMsg('chamilo-msg', '❌ ' + result.error, 'fail');
        }
    } catch (e) {
        setStatus('chamilo-status', 'fail');
        showMsg('chamilo-msg', '❌ Нет связи', 'fail');
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
            showMsg('llm-msg', '✅ ' + result.message, 'ok');
        } else {
            setStatus('llm-status', 'fail');
            showMsg('llm-msg', '❌ ' + result.error, 'fail');
        }
    } catch (e) {
        setStatus('llm-status', 'fail');
        showMsg('llm-msg', '❌ Нет связи', 'fail');
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
    btn.innerHTML = '⏳ Генерация...';

    showProgress('Генерация курса через ИИ... Это может занять 1-3 минуты.');

    const settings = getSettings();

    try {
        const result = await api('/api/generate', {
            topic,
            pages: document.getElementById('pages').value,
            lang: document.getElementById('lang').value,
            base_url: settings.llm_base_url,
            model: settings.llm_model,
            api_key: settings.llm_api_key,
            temperature: parseFloat(document.getElementById('temperature').value),
            max_tokens: parseInt(document.getElementById('max-tokens').value),
            blocks_per_page: parseInt(document.getElementById('blocks-per-page').value),
            questions_per_page: parseInt(document.getElementById('questions-per-page').value),
            detail_level: document.getElementById('detail-level').value,
            system_prompt: document.getElementById('system-prompt').value.trim(),
            extra_instructions: document.getElementById('extra-instructions').value.trim(),
        });

        hideProgress();

        if (result.ok) {
            lastCourse = result.course;
            renderPreview(result.course);
            // Auto-build SCORM
            await buildSCORM();
        } else {
            showMsg('action-msg', '❌ ' + result.error, 'fail');
        }
    } catch (e) {
        hideProgress();
        showMsg('action-msg', '❌ Ошибка сети', 'fail');
    }

    btn.disabled = false;
    btn.innerHTML = '🤖 Сгенерировать';
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
            document.getElementById('file-drop').innerHTML = '✅ ' + file.name;
            document.getElementById('file-drop').classList.add('active');

            lastCourse = course;
            await api('/api/generate-from-json', { course });
            renderPreview(course);
            await buildSCORM();
        } catch (err) {
            document.getElementById('file-drop').innerHTML = '❌ Ошибка JSON: ' + err.message;
        }
    };
    reader.readAsText(file);
}

// ═══════════════════════════════════════════
//  Preview
// ═══════════════════════════════════════════

function renderPreview(course) {
    const section = document.getElementById('preview-section');
    section.style.display = '';

    // Auto-load Chamilo courses
    loadChamiloCourses();

    // Header
    const pages = course.pages || [];
    const totalBlocks = pages.reduce((s, p) => s + (p.blocks || []).length, 0);
    const quizBlocks = pages.reduce((s, p) => s + (p.blocks || []).filter(b => b.type === 'mcq' || b.type === 'truefalse').length, 0);

    document.getElementById('course-header').innerHTML = `
        <div class="course-title">${course.title || 'Без названия'}</div>
        <div class="course-desc">${course.description || ''}</div>
        <div class="course-stats">
            <div class="stat">📄 <span>${pages.length}</span> страниц</div>
            <div class="stat">📝 <span>${totalBlocks}</span> блоков</div>
            <div class="stat">❓ <span>${quizBlocks}</span> вопросов</div>
        </div>
    `;

    // Pages
    let pagesHTML = '';
    pages.forEach((page, i) => {
        const blocks = (page.blocks || []).map(b => {
            const icon = b.type === 'text' ? '📖' : b.type === 'mcq' ? '❓' : '✅';
            const label = b.type === 'text' ? 'Теория' : b.type === 'mcq' ? 'MCQ' : 'True/False';
            return `<div class="block-item"><span class="block-icon">${icon}</span> <strong>${label}:</strong> ${b.title || ''}</div>`;
        }).join('');

        pagesHTML += `
            <div class="page-card${i === 0 ? ' open' : ''}" onclick="this.classList.toggle('open')">
                <div class="page-card-header">
                    <span class="page-num">${i + 1}</span>
                    ${page.title || 'Страница ' + (i + 1)}
                </div>
                <div class="page-card-body">${blocks}</div>
            </div>
        `;
    });
    document.getElementById('course-pages').innerHTML = pagesHTML;

    section.scrollIntoView({ behavior: 'smooth' });
}

// ═══════════════════════════════════════════
//  SCORM Build & Upload
// ═══════════════════════════════════════════

async function buildSCORM() {
    try {
        const result = await api('/api/build-scorm', {});
        if (result.ok) {
            lastScormFilename = result.filename;
            showMsg('action-msg', '✅ SCORM создан: ' + result.filename, 'ok');
        } else {
            showMsg('action-msg', '❌ ' + result.error, 'fail');
        }
    } catch (e) {
        showMsg('action-msg', '❌ Ошибка сборки', 'fail');
    }
}

function downloadSCORM() {
    if (lastScormFilename) {
        window.open('/api/download/' + lastScormFilename, '_blank');
    } else {
        showMsg('action-msg', '⚠️ Сначала сгенерируйте курс', 'fail');
    }
}

async function uploadToChamilo() {
    const selectVal = document.getElementById('chamilo-course-select').value;
    const manualVal = document.getElementById('chamilo-course-manual').value.trim();
    const courseCode = manualVal || selectVal;

    if (!courseCode) {
        showMsg('action-msg', '⚠️ Выберите курс из списка или введите код курса вручную', 'fail');
        return;
    }

    const btn = document.getElementById('btn-upload');
    btn.disabled = true;
    btn.innerHTML = '⏳ Загрузка...';

    try {
        const result = await api('/api/upload', {
            course_code: courseCode,
            chamilo_url: document.getElementById('chamilo-url').value.trim(),
            chamilo_user: document.getElementById('chamilo-user').value.trim() || 'admin',
            chamilo_password: document.getElementById('chamilo-pass').value.trim(),
        });

        if (result.ok) {
            showMsg('action-msg', '🎉 ' + result.message, 'ok');
        } else {
            showMsg('action-msg', '❌ ' + result.error, 'fail');
        }
    } catch (e) {
        showMsg('action-msg', '❌ Ошибка загрузки', 'fail');
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
        el.textContent = '⏳...';
    } else {
        el.textContent = text || 'Проверить';
    }
}

function showProgress(text) {
    const section = document.getElementById('progress-section');
    section.style.display = '';
    document.getElementById('progress-text').textContent = text;

    // Animate progress
    const bar = document.getElementById('gen-progress');
    bar.style.width = '10%';
    let w = 10;
    window._progressInterval = setInterval(() => {
        w = Math.min(w + Math.random() * 5, 90);
        bar.style.width = w + '%';
    }, 2000);
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
