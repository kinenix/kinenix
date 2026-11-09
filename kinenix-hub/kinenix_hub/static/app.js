let allExecutions = [];
let currentFilter = 'all';

async function loadDashboardData() {
  try {
    // 1. Fetch Workers
    const resWorkers = await fetch('/api/v1/workers');
    if (resWorkers.ok) {
      const dataWorkers = await resWorkers.json();
      renderWorkers(dataWorkers.workers || []);
    }

    // 2. Fetch Executions
    const resExec = await fetch('/api/v1/executions?limit=50');
    if (resExec.ok) {
      const dataExec = await resExec.json();
      allExecutions = dataExec.executions || [];
      renderKPIs(allExecutions);
      renderExecutions(allExecutions);
    }
  } catch (err) {
    console.warn('Dashboard data fetch error:', err);
  }
}

// A run that finished, but with failed work items or steps on the way (#110)
function isPartial(e) {
  return !e.has_error && e.status === 'partial';
}

// Stopped on request: not a failure and not a success (#166)
function isInterrupted(e) {
  return e.status === 'interrupted';
}

function partialText(e) {
  const d = e.details || {};
  if (d.items_total && d.items_failed) return `${d.items_failed} จาก ${d.items_total} รายการไม่สำเร็จ`;
  if (d.failure_count) return `มี ${d.failure_count} ขั้นตอนที่ไม่สำเร็จ`;
  return 'มีบางขั้นตอนที่ไม่สำเร็จ';
}

function renderKPIs(executions) {
  const total = executions.length;
  const failed = executions.filter(e => !isInterrupted(e) && (e.has_error || e.status === 'failed')).length;
  const partial = executions.filter(isPartial).length;
  const success = executions.filter(e => e.status === 'success').length;
  const rate = total > 0 ? Math.round((success / total) * 100) : 100;

  document.getElementById('kpi-executions-total').innerText = total;
  document.getElementById('kpi-success-rate').innerText =
    `${rate}% ความสำเร็จ (${success} สำเร็จ, ${partial} สำเร็จบางส่วน, ${failed} ผิดพลาด)`;
  document.getElementById('kpi-triages-total').innerText = failed;
}

function renderWorkers(workers) {
  const container = document.getElementById('workers-container');
  const onlineCount = workers.filter(w => w.status !== 'offline').length;
  
  document.getElementById('kpi-workers-online').innerText = `${onlineCount} Online`;
  document.getElementById('kpi-workers-total').innerText = `${workers.length} Nodes`;

  if (workers.length === 0) {
    container.innerHTML = `
      <div class="col-span-full py-8 text-center bg-slate-900/40 border border-dashed border-slate-800 rounded-2xl text-slate-400 text-xs">
        ยังไม่มีเครื่องลูกข่ายเชื่อมต่อเข้ามา (ระบบจะเพิ่มอัตโนมัติเมื่อ Worker ส่ง Heartbeat หรือรันงาน)
      </div>
    `;
    return;
  }

  // Every value from a worker is escaped: workers are remote machines, and error text can carry content from web pages
  container.innerHTML = workers.map(w => {
    const isOnline = w.status !== 'offline';
    const statusBg = isOnline ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : 'bg-slate-700/50 text-slate-400 border-slate-600';

    return `
      <div class="bg-slate-900 border border-slate-800 rounded-2xl p-5 hover:border-slate-700 transition shadow-sm">
        <div class="flex justify-between items-start mb-3">
          <div class="flex items-center gap-3">
            <div class="w-9 h-9 rounded-xl bg-slate-800/80 border border-slate-700 flex items-center justify-center text-[10px] font-bold text-slate-300">
              ${osBadge(w.os_info)}
            </div>
            <div>
              <h3 class="font-bold text-sm text-slate-100 flex items-center gap-2">
                ${escapeHtml(w.name || w.id)}
                <span class="text-[10px] px-2 py-0.5 rounded-full border ${statusBg}">
                  ${escapeHtml(w.status)}
                </span>
              </h3>
              <p class="text-xs text-slate-400">${escapeHtml(w.os_info)} • IP: ${escapeHtml(w.ip_address)}</p>
            </div>
          </div>
          <span class="text-[11px] text-slate-500">${formatTimeAgo(w.last_heartbeat)}</span>
        </div>

        <div class="space-y-1.5 mt-4 text-xs border-t border-slate-800/80 pt-3">
          <div class="flex justify-between text-slate-300">
            <span class="text-slate-400">Current Task:</span>
            <span class="font-mono ${w.current_task ? 'text-amber-300 font-semibold' : 'text-slate-400'}">
              ${escapeHtml(w.current_task || 'Idle (สแตนด์บาย)')}
            </span>
          </div>
          <div class="flex items-center gap-4 text-slate-400 pt-1">
            <span>CPU: <strong class="text-slate-200">${escapeHtml(w.cpu_percent || 0)}%</strong></span>
            <span>RAM: <strong class="text-slate-200">${escapeHtml(w.ram_usage || 'N/A')}</strong></span>
            <span>LLM: <strong class="text-slate-400 italic">None (Central API)</strong></span>
          </div>
        </div>
      </div>
    `;
  }).join('');
}

function renderExecutions(executions) {
  const tbody = document.getElementById('executions-tbody');
  let filtered = executions;

  if (currentFilter === 'failed') {
    filtered = executions.filter(e => !isInterrupted(e) && (e.has_error || e.status === 'failed'));
  } else if (currentFilter === 'partial') {
    filtered = executions.filter(isPartial);
  } else if (currentFilter === 'success') {
    filtered = executions.filter(e => !e.has_error && e.status === 'success');
  }

  if (filtered.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="6" class="py-8 text-center text-slate-500 text-xs">
          ไม่พบรายการประวัติการรันตามเงื่อนไขที่เลือก
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = filtered.map(e => {
    const isError = !isInterrupted(e) && (e.has_error || e.status === 'failed');
    const statusPill = isInterrupted(e)
      ? `<span class="px-2.5 py-0.5 rounded-full text-[11px] font-medium bg-slate-500/15 text-slate-300 border border-slate-500/30">หยุดตามคำสั่ง</span>`
      : isError
      ? `<span class="px-2.5 py-0.5 rounded-full text-[11px] font-medium bg-rose-500/15 text-rose-400 border border-rose-500/30">ล้มเหลว (${escapeHtml(e.failed_step_name || e.failed_step_id || 'Error')})</span>`
      : isPartial(e)
        ? `<span class="px-2.5 py-0.5 rounded-full text-[11px] font-medium bg-amber-500/15 text-amber-300 border border-amber-500/30">สำเร็จบางส่วน · ${escapeHtml(partialText(e))}</span>`
        : `<span class="px-2.5 py-0.5 rounded-full text-[11px] font-medium bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">สำเร็จ</span>`;

    // The ID travels as data (data-id), never inside the onclick JavaScript, so no value can become code
    const stepsButton = `<button data-id="${escapeHtml(e.id)}" onclick="openStepsModal(this.dataset.id)" class="px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 font-medium transition">
          ดู Steps
        </button>`;
    const actionCell = isError
      ? `<div class="inline-flex gap-2">${stepsButton}<button data-id="${escapeHtml(e.id)}" onclick="openModal(this.dataset.id)" class="px-2.5 py-1 rounded-lg bg-indigo-500/20 hover:bg-indigo-500/30 text-indigo-300 border border-indigo-500/30 font-medium inline-flex items-center gap-1.5 transition">
          ดู AI สรุป
        </button></div>`
      : stepsButton;

    const timeFormatted = formatDateTime(e.start_time);
    const duration = e.duration_seconds ? `${e.duration_seconds.toFixed(1)}s` : '-';

    return `
      <tr class="hover:bg-slate-800/40 transition">
        <td class="py-3.5 px-4 font-mono text-slate-400">${timeFormatted}</td>
        <td class="py-3.5 px-4 font-semibold text-slate-100">${escapeHtml(e.flow_name)}</td>
        <td class="py-3.5 px-4 font-mono text-slate-300">${escapeHtml(e.worker_id)}</td>
        <td class="py-3.5 px-4">${duration}</td>
        <td class="py-3.5 px-4">${statusPill}</td>
        <td class="py-3.5 px-4 text-right">${actionCell}</td>
      </tr>
    `;
  }).join('');
}

function filterExecutions(filter) {
  currentFilter = filter;
  ['all', 'failed', 'partial', 'success'].forEach(f => {
    const btn = document.getElementById(`filter-${f}`);
    if (f === filter) {
      btn.className = 'text-xs px-3 py-1.5 rounded-lg bg-sky-600 text-white font-medium transition';
    } else {
      btn.className = 'text-xs px-3 py-1.5 rounded-lg bg-slate-800 text-slate-300 hover:bg-slate-700 font-medium transition';
    }
  });
  renderExecutions(allExecutions);
}

function openModal(executionId) {
  const item = allExecutions.find(e => e.id === executionId);
  if (!item) return;

  document.getElementById('modal-flow-name').innerText = `Flow: ${item.flow_name} (${item.failed_step_name || item.failed_step_id || 'Failed Step'})`;
  document.getElementById('modal-worker-info').innerText = `Worker Node: ${item.worker_id} • เวลา: ${formatDateTime(item.start_time)}`;
  
  document.getElementById('modal-confidence').innerText = item.ai_confidence ? `Confidence: ${item.ai_confidence}%` : 'Classified';
  document.getElementById('modal-summary').innerText = item.ai_summary || item.error_message || 'ไม่มีบทสรุป AI';
  document.getElementById('modal-root-cause').innerText = item.ai_root_cause || item.error_type || '-';
  document.getElementById('modal-suggestion').innerText = item.ai_suggestion || 'ตรวจสอบ Log หรือคอนฟิกพารามิเตอร์ของ Step';

  document.getElementById('modal-traceback').innerText = item.error_message 
    ? `${item.exception_class || 'Exception'}: ${item.error_message}\nStep: ${item.failed_step_id} (${item.failed_step_name})`
    : 'No traceback details recorded.';

  document.getElementById('ai-modal').classList.remove('hidden');
}

function closeModal() {
  document.getElementById('ai-modal').classList.add('hidden');
}

// Values from workers are escaped before being placed in HTML (see renderWorkers and renderExecutions)
function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// Short text badge for the worker's operating system (no emoji, per project rules)
function osBadge(osInfo) {
  const os = String(osInfo || '').toLowerCase();
  if (os.includes('rasp') || os.includes('aarch64') || os.includes('arm')) return 'Pi';
  if (os.includes('linux') || os.includes('ubuntu')) return 'LNX';
  if (os.includes('windows')) return 'WIN';
  if (os.includes('darwin') || os.includes('mac')) return 'MAC';
  return 'PC';
}

const STEP_STATUS_CLASSES = {
  success: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
  failed: 'bg-rose-500/15 text-rose-400 border-rose-500/30',
  skipped: 'bg-slate-700/50 text-slate-400 border-slate-600',
};

async function openStepsModal(executionId) {
  const tbody = document.getElementById('steps-tbody');
  document.getElementById('steps-title').innerText = 'Steps';
  document.getElementById('steps-subtitle').innerText = '';
  tbody.innerHTML = '<tr><td colspan="6" class="py-6 text-center text-slate-500">กำลังโหลด...</td></tr>';
  document.getElementById('steps-modal').classList.remove('hidden');

  try {
    const res = await fetch(`/api/v1/executions/${encodeURIComponent(executionId)}/steps`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const e = data.execution;
    const steps = data.steps || [];

    document.getElementById('steps-title').innerText = `${e.flow_name} (${steps.length} steps)`;
    document.getElementById('steps-subtitle').innerText =
      `Worker: ${e.worker_id} • ${isPartial(e) ? 'สำเร็จบางส่วน: ' + partialText(e) : e.status} • ${(e.duration_seconds || 0).toFixed(1)}s • ID: ${e.id}`;

    if (steps.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" class="py-6 text-center text-slate-500">ไม่มีรายละเอียด step สำหรับการรันนี้</td></tr>';
      return;
    }

    tbody.innerHTML = steps.map((s, i) => {
      const status = escapeHtml(s.status || '-');
      const pill = STEP_STATUS_CLASSES[s.status] || STEP_STATUS_CLASSES.skipped;
      const duration = typeof s.duration_seconds === 'number' ? `${s.duration_seconds.toFixed(1)}s` : '-';
      const error = s.error_message ? `${s.error_type ? s.error_type + ': ' : ''}${s.error_message}` : '';
      // The worker's diagnosis first (#111); the full message stays one click away
      const errorCell = s.root_cause
        ? `<div class="text-rose-200">${escapeHtml(s.root_cause)}</div>
           ${s.suggested_fix ? `<div class="mt-1 text-amber-300">วิธีแก้: ${escapeHtml(s.suggested_fix)}</div>` : ''}
           ${error ? `<details class="mt-1 text-slate-400"><summary class="cursor-pointer">ข้อความเต็ม</summary><pre class="whitespace-pre-wrap text-[10px]">${escapeHtml(error)}</pre></details>` : ''}`
        : escapeHtml(error);
      const item = s.item ? `<div class="text-[10px] text-slate-400">รายการ: ${escapeHtml(s.item)}</div>` : '';
      return `
        <tr class="${s.status === 'failed' ? 'bg-rose-950/30' : ''}">
          <td class="py-2 px-3 text-slate-500 font-mono">${i + 1}</td>
          <td class="py-2 px-3 text-slate-100">${escapeHtml(s.step_name || s.step_id)}${item}</td>
          <td class="py-2 px-3 text-slate-400 font-mono">${escapeHtml(s.action)}</td>
          <td class="py-2 px-3"><span class="px-2 py-0.5 rounded-full text-[10px] border ${pill}">${status}</span></td>
          <td class="py-2 px-3 font-mono text-slate-300">${duration}</td>
          <td class="py-2 px-3 text-rose-300 break-words">${errorCell}</td>
        </tr>`;
    }).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" class="py-6 text-center text-rose-400">โหลดไม่สำเร็จ (${escapeHtml(err.message)})</td></tr>`;
  }
}

function closeStepsModal() {
  document.getElementById('steps-modal').classList.add('hidden');
}

// Date and time in the browser's time zone, e.g. 2026-11-03 12:28:44: the list spans several days,
// so a time alone does not say which run is which
function formatDateTime(isoString) {
  if (!isoString) return '-';
  const d = new Date(isoString);
  if (isNaN(d)) return '-';
  const pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function formatTimeAgo(isoString) {
  if (!isoString) return '-';
  const diff = Math.floor((new Date() - new Date(isoString)) / 1000);
  if (diff < 5) return 'Just now';
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}

// Auto load and poll every 4 seconds
loadDashboardData();
setInterval(loadDashboardData, 4000);

