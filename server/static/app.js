// AP Automation Console Application Client
let currentInvoiceId = null;
let currentResult = null;
let activePOId = null;
const poCache = {};
let activeRuleFilter = 'all';

// Safe DOM Helper Utilities
function $(id) {
  return document.getElementById(id);
}

function setHtml(id, html) {
  const el = $(id);
  if (el) el.innerHTML = html;
  return el;
}

function setText(id, text) {
  const el = $(id);
  if (el) el.textContent = text;
  return el;
}

function setDisplay(id, show) {
  const el = $(id);
  if (el) {
    if (show) el.classList.remove('hidden');
    else el.classList.add('hidden');
  }
  return el;
}

function debounce(fn, delayMs = 250) {
  let timer = null;
  return function(...args) {
    clearTimeout(timer);
    timer = setTimeout(() => fn.apply(this, args), delayMs);
  };
}

/* ==========================================================================
   PRODUCTION DATA CACHE LAYER (Memory + SessionStorage + SWR)
   ========================================================================== */
class ClientDataCache {
  constructor() {
    this.memory = new Map();
    this.sessionPrefix = 'ap_cache_v1:';
  }

  get(key) {
    const entry = this.memory.get(key);
    const now = Date.now();
    if (entry && entry.expiresAt > now) {
      return entry.data;
    }
    try {
      const raw = sessionStorage.getItem(this.sessionPrefix + key);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (parsed.expiresAt > now) {
          this.memory.set(key, parsed);
          return parsed.data;
        } else {
          sessionStorage.removeItem(this.sessionPrefix + key);
        }
      }
    } catch (_) {}
    return null;
  }

  set(key, data, ttlSeconds = 60) {
    const entry = {
      data,
      expiresAt: Date.now() + (ttlSeconds * 1000)
    };
    this.memory.set(key, entry);
    try {
      sessionStorage.setItem(this.sessionPrefix + key, JSON.stringify(entry));
    } catch (_) {}
  }

  invalidate(pattern) {
    for (const k of Array.from(this.memory.keys())) {
      if (!pattern || k.includes(pattern)) {
        this.memory.delete(k);
      }
    }
    try {
      for (let i = sessionStorage.length - 1; i >= 0; i--) {
        const k = sessionStorage.key(i);
        if (k && k.startsWith(this.sessionPrefix)) {
          const stripped = k.slice(this.sessionPrefix.length);
          if (!pattern || stripped.includes(pattern)) {
            sessionStorage.removeItem(k);
          }
        }
      }
    } catch (_) {}
  }

  async fetchWithCache(url, { ttl = 60, swr = true } = {}) {
    const cached = this.get(url);
    if (cached) {
      if (swr) {
        fetch(url)
          .then(r => r.ok ? r.json() : null)
          .then(fresh => {
            if (fresh) this.set(url, fresh, ttl);
          })
          .catch(() => {});
      }
      return cached;
    }
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    this.set(url, data, ttl);
    return data;
  }
}
const DataCache = new ClientDataCache();

/* ==========================================================================
   CLIENT-SIDE HASH ROUTER
   ========================================================================== */
class ClientRouter {
  constructor() {
    this.routes = [];
    this.currentPath = null;
    window.addEventListener('hashchange', () => this.resolve());
  }

  add(pattern, handler) {
    const paramNames = [];
    const regexPath = pattern.replace(/:([a-zA-Z0-9_]+)/g, (_, name) => {
      paramNames.push(name);
      return '([^/?#]+)';
    });
    const regex = new RegExp(`^${regexPath}$`);
    this.routes.push({ pattern, regex, paramNames, handler });
    return this;
  }

  navigate(path, { replace = false } = {}) {
    if (replace) {
      const base = window.location.href.split('#')[0];
      window.location.replace(`${base}#${path}`);
    } else {
      window.location.hash = path;
    }
  }

  resolve() {
    const fullHash = window.location.hash.slice(1) || '/cockpit';
    const [pathPart, queryPart] = fullHash.split('?');
    const cleanPath = pathPart || '/cockpit';
    this.currentPath = cleanPath;

    const query = {};
    if (queryPart) {
      const searchParams = new URLSearchParams(queryPart);
      for (const [k, v] of searchParams.entries()) {
        query[k] = v;
      }
    }

    for (const route of this.routes) {
      const match = cleanPath.match(route.regex);
      if (match) {
        const params = {};
        route.paramNames.forEach((name, i) => {
          params[name] = decodeURIComponent(match[i + 1] || '');
        });
        route.handler({ params, query, path: cleanPath, fullHash });
        return;
      }
    }

    // Fallback to /cockpit
    this.navigate('/cockpit', { replace: true });
  }
}
const AppRouter = new ClientRouter();

let allHistoryInvoices = [];
let activeSidebarFilter = 'all';
let sidebarSearchQuery = '';
let sidebarQueueOffset = 0;
const SIDEBAR_QUEUE_LIMIT = 30;
let sidebarQueueHasMore = true;
let sidebarQueueLoading = false;

document.addEventListener('DOMContentLoaded', () => {
  initWorkspaceNav();
  initSidebarToggle();
  initSidebarTabs();
  initSidebarFilters();
  initDropZone();
  initTabs();
  initRuleFilters();
  initBatchWorkspace();
  initPOHub();
  initDocumentViewerModal();

  const btnProcess = $('btn-process');
  if (btnProcess) btnProcess.addEventListener('click', handleProcess);

  const btnSeed = $('btn-seed-demo');
  if (btnSeed) btnSeed.addEventListener('click', handleSeedDemo);

  const btnApprove = $('btn-review-approve');
  if (btnApprove) btnApprove.addEventListener('click', () => handleResolve('approve'));

  const btnReject = $('btn-review-reject');
  if (btnReject) btnReject.addEventListener('click', () => handleResolve('reject'));

  // Initialize Route Handlers
  initAppRoutes();

  // Resolve active route on startup
  AppRouter.resolve();
});

function initSidebarToggle() {
  const toggleBtn = $('sidebar-toggle-btn');
  const aside = $('left-rail');
  const icon = $('collapse-icon');
  const btnUpload = $('btn-rail-upload');
  const btnHistory = $('btn-rail-history');
  const btnExpand = $('btn-rail-expand');

  if (toggleBtn && aside) {
    toggleBtn.addEventListener('click', () => {
      aside.classList.toggle('sidebar-collapsed');
      const isCollapsed = aside.classList.contains('sidebar-collapsed');
      if (icon) icon.textContent = isCollapsed ? 'last_page' : 'first_page';
    });
  }

  const expandRail = () => {
    if (aside && aside.classList.contains('sidebar-collapsed')) {
      aside.classList.remove('sidebar-collapsed');
      if (icon) icon.textContent = 'first_page';
    }
  };

  if (btnUpload) {
    btnUpload.addEventListener('click', () => {
      expandRail();
      if (window.switchSidebarTab) window.switchSidebarTab('ingest');
    });
  }

  if (btnHistory) {
    btnHistory.addEventListener('click', () => {
      expandRail();
      if (window.switchSidebarTab) window.switchSidebarTab('queue');
    });
  }

  if (btnExpand) {
    btnExpand.addEventListener('click', expandRail);
  }
}

function initSidebarTabs() {
  const btnQueue = $('tab-btn-queue');
  const btnIngest = $('tab-btn-ingest');
  const panelQueue = $('panel-queue');
  const panelIngest = $('panel-ingest');
  const btnSwitchToQueue = $('btn-switch-to-queue');

  window.switchSidebarTab = function(mode) {
    if (mode === 'ingest') {
      if (panelQueue) { panelQueue.classList.add('hidden'); panelQueue.classList.remove('flex'); }
      if (panelIngest) { panelIngest.classList.remove('hidden'); panelIngest.classList.add('flex'); }
      if (btnIngest) {
        btnIngest.className = 'py-2 px-1 font-semibold text-amber-400 border-b-2 border-amber-500 bg-[#161f2c] flex items-center justify-center gap-1.5 transition-colors uppercase cursor-pointer';
      }
      if (btnQueue) {
        btnQueue.className = 'py-2 px-1 text-[#94a3b8] hover:text-[#dee2ee] hover:bg-[#131a24] flex items-center justify-center gap-1.5 transition-colors uppercase border-b-2 border-transparent cursor-pointer';
      }
    } else {
      if (panelIngest) { panelIngest.classList.add('hidden'); panelIngest.classList.remove('flex'); }
      if (panelQueue) { panelQueue.classList.remove('hidden'); panelQueue.classList.add('flex'); }
      if (btnQueue) {
        btnQueue.className = 'py-2 px-1 font-semibold text-amber-400 border-b-2 border-amber-500 bg-[#161f2c] flex items-center justify-center gap-1.5 transition-colors uppercase cursor-pointer';
      }
      if (btnIngest) {
        btnIngest.className = 'py-2 px-1 text-[#94a3b8] hover:text-[#dee2ee] hover:bg-[#131a24] flex items-center justify-center gap-1.5 transition-colors uppercase border-b-2 border-transparent cursor-pointer';
      }
    }
  };

  if (btnQueue) {
    btnQueue.addEventListener('click', () => {
      window.switchSidebarTab('queue');
    });
  }
  if (btnIngest) {
    btnIngest.addEventListener('click', () => {
      window.switchSidebarTab('ingest');
    });
  }
  if (btnSwitchToQueue) {
    btnSwitchToQueue.addEventListener('click', () => {
      window.switchSidebarTab('queue');
    });
  }
}

function initSidebarFilters() {
  const searchInput = $('sidebar-search-input');
  if (searchInput) {
    const debouncedQueueSearch = debounce((val) => {
      sidebarSearchQuery = val;
      loadCockpitQueue({ reset: true });
    }, 250);

    searchInput.addEventListener('input', (e) => {
      debouncedQueueSearch(e.target.value.trim().toLowerCase());
    });
  }

  const chips = document.querySelectorAll('.sidebar-chip');
  chips.forEach(chip => {
    chip.addEventListener('click', () => {
      chips.forEach(c => {
        c.className = 'sidebar-chip px-2 py-0.5 bg-[#161f2c] border border-[#232f42] text-[#94a3b8] hover:text-[#dee2ee] transition whitespace-nowrap cursor-pointer';
        c.classList.remove('active');
      });
      chip.className = 'sidebar-chip px-2 py-0.5 bg-amber-500 text-slate-950 font-bold whitespace-nowrap active cursor-pointer';
      activeSidebarFilter = chip.dataset.filter || 'all';
      loadCockpitQueue({ reset: true });
    });
  });

  const panelQueue = $('panel-queue');
  if (panelQueue) {
    panelQueue.addEventListener('scroll', () => {
      if (sidebarQueueLoading || !sidebarQueueHasMore) return;
      if (panelQueue.scrollTop + panelQueue.clientHeight >= panelQueue.scrollHeight - 120) {
        loadCockpitQueue({ reset: false });
      }
    });
  }
}

function initDropZone() {
  const dropZone = $('drop-zone');
  const fileInput = $('file-input');
  const btnProcess = $('btn-process');
  if (!dropZone || !fileInput) return;

  fileInput.addEventListener('change', () => {
    if (fileInput.files.length > 0) {
      const hint = dropZone.querySelector('.hint');
      if (hint) hint.textContent = `Selected: ${fileInput.files[0].name}`;
      if (btnProcess) btnProcess.disabled = false;
    }
  });

  dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('drag-over');
  });

  dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));

  dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('drag-over');
    if (e.dataTransfer.files.length > 0) {
      fileInput.files = e.dataTransfer.files;
      const hint = dropZone.querySelector('.hint');
      if (hint) hint.textContent = `Selected: ${fileInput.files[0].name}`;
      if (btnProcess) btnProcess.disabled = false;
    }
  });
}

function initTabs() {
  const tabs = document.querySelectorAll('.tab-btn');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      tabs.forEach(t => {
        t.classList.remove('active', 'border-b-2', 'border-amber-500', 'text-amber-400', 'bg-[#161f2c]', 'font-semibold');
        t.classList.add('text-[#94a3b8]');
      });
      document.querySelectorAll('.tab-content').forEach(c => {
        c.classList.remove('active');
        c.classList.add('hidden');
      });

      tab.classList.add('active', 'border-b-2', 'border-amber-500', 'text-amber-400', 'bg-[#161f2c]', 'font-semibold');
      tab.classList.remove('text-[#94a3b8]');
      const target = $(tab.dataset.tab);
      if (target) {
        target.classList.add('active');
        target.classList.remove('hidden');
      }
    });
  });
}

function initRuleFilters() {
  const filterBtns = document.querySelectorAll('.rule-filter-btn');
  filterBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      filterBtns.forEach(b => {
        b.classList.remove('active', 'bg-amber-500', 'text-slate-950', 'font-semibold');
        b.classList.add('text-[#94a3b8]');
      });
      btn.classList.add('active', 'bg-amber-500', 'text-slate-950', 'font-semibold');
      btn.classList.remove('text-[#94a3b8]');
      activeRuleFilter = btn.dataset.filter;
      if (currentResult && currentResult.checks) {
        renderRules(currentResult.checks, activeRuleFilter);
      }
    });
  });
}

class PacedProgressManager {
  constructor(onUpdate, minDwellMs = 900) {
    this.onUpdate = onUpdate;
    this.minDwellMs = minDwellMs;
    this.queue = [];
    this.isProcessing = false;
    this.currentStep = null;
    this.lastChangeTime = 0;
  }

  enqueue(step) {
    this.queue.push(step);
    if (!this.isProcessing) {
      this._drain();
    }
  }

  async _drain() {
    this.isProcessing = true;
    while (this.queue.length > 0) {
      const step = this.queue.shift();
      const now = Date.now();
      const elapsedSinceLast = now - this.lastChangeTime;
      if (this.currentStep && elapsedSinceLast < this.minDwellMs) {
        await new Promise(r => setTimeout(r, this.minDwellMs - elapsedSinceLast));
      }
      this.currentStep = step;
      this.lastChangeTime = Date.now();
      this.onUpdate(step);
    }
    this.isProcessing = false;
  }

  async finish() {
    while (this.isProcessing || this.queue.length > 0) {
      await new Promise(r => setTimeout(r, 40));
    }
    const elapsed = Date.now() - this.lastChangeTime;
    if (elapsed < 600) {
      await new Promise(r => setTimeout(r, 600 - elapsed));
    }
  }
}

async function handleProcess() {
  const fileInput = $('file-input');
  if (!fileInput || !fileInput.files.length) return;

  const ocrEngine = $('ocr-select') ? $('ocr-select').value : '';
  const isDryRun = $('dryrun-toggle') ? $('dryrun-toggle').checked : false;
  const btnProcess = $('btn-process');

  const formData = new FormData();
  formData.append('file', fileInput.files[0]);

  const progressCard = $('processing-spinner');
  const stageBadge = $('spinner-stage-badge');
  const spinnerText = $('spinner-text');
  const barFill = $('spinner-bar-fill');
  const timerLabel = $('spinner-timer');

  if (btnProcess) btnProcess.disabled = true;
  if (progressCard) progressCard.classList.remove('hidden');

  const startTime = Date.now();
  const timerInterval = setInterval(() => {
    if (timerLabel) {
      const sec = ((Date.now() - startTime) / 1000).toFixed(1);
      timerLabel.textContent = `${sec}s`;
    }
  }, 100);

  // Crisp stage mapper
  const stageMap = {
    ingest: { badge: 'Step 1 of 4', text: 'Extracting text...', pct: 25 },
    extraction: { badge: 'Step 2 of 4', text: 'Extracting invoice fields and items...', pct: 50 },
    matching: { badge: 'Step 3 of 4', text: 'Matching purchase orders...', pct: 75 },
    explanation: { badge: 'Step 4 of 4', text: 'Validating rules & generating AP reasoning...', pct: 95 },
    complete: { badge: 'Complete', text: 'Finalizing decision...', pct: 100 },
    cache: { badge: 'Cached', text: 'Retrieved from cache...', pct: 100 },
  };

  const pacer = new PacedProgressManager((step) => {
    if (stageBadge) stageBadge.textContent = step.badge;
    if (spinnerText) spinnerText.textContent = step.text;
    if (barFill) barFill.style.width = `${step.pct}%`;
  }, 900);

  // Initial stage
  pacer.enqueue(stageMap.ingest);

  let streamUrl = `/api/invoices/process/stream?dry_run=${isDryRun}`;
  if (ocrEngine) streamUrl += `&ocr_engine=${ocrEngine}`;

  try {
    const res = await fetch(streamUrl, { method: 'POST', body: formData });
    if (!res.ok) throw new Error(`Server returned ${res.status}`);

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let finalResult = null;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const blocks = buffer.split('\n\n');
      buffer = blocks.pop() || '';

      for (const block of blocks) {
        if (!block.trim()) continue;
        const line = block.split('\n').find(l => l.startsWith('data: '));
        if (!line) continue;
        try {
          const payload = JSON.parse(line.replace(/^data:\s*/, ''));
          if (payload.type === 'progress' && stageMap[payload.stage]) {
            pacer.enqueue(stageMap[payload.stage]);
          } else if (payload.type === 'complete' && payload.result) {
            finalResult = payload.result;
          } else if (payload.type === 'error') {
            throw new Error(payload.error || 'Pipeline error');
          }
        } catch (e) {
          console.warn('SSE parse error:', e);
        }
      }
    }

    await pacer.finish();

    if (finalResult) {
      DataCache.invalidate('invoices');
      DataCache.invalidate('pos');
      await renderDecisionResult(finalResult);
      if (window.switchSidebarTab) window.switchSidebarTab('queue');
      await loadCockpitQueue({ reset: true });
      if (finalResult.invoice_id) {
        AppRouter.navigate(`/cockpit/invoices/${finalResult.invoice_id}`, { replace: true });
      }
    } else {
      throw new Error('No decision result returned from pipeline.');
    }
  } catch (err) {
    alert(`Error processing invoice: ${err.message}`);
  } finally {
    clearInterval(timerInterval);
    if (btnProcess) btnProcess.disabled = false;
    if (progressCard) progressCard.classList.add('hidden');
  }
}

function getConfidenceTier(val) {
  const score = Number(val) || 0;
  if (score >= 0.85) {
    return { tier: 'green', label: 'High', cssClass: 'conf-high', barColor: '#16a34a' };
  } else if (score >= 0.60) {
    return { tier: 'amber', label: 'Moderate', cssClass: 'conf-med', barColor: '#d97706' };
  } else {
    return { tier: 'red', label: 'Low', cssClass: 'conf-low', barColor: '#dc2626' };
  }
}

async function fetchPODetail(poId) {
  if (!poId) return null;
  if (poCache[poId]) return poCache[poId];
  try {
    const res = await fetch(`/api/pos/${encodeURIComponent(poId)}`);
    if (!res.ok) return null;
    const data = await res.json();
    if (!data.error) {
      poCache[poId] = data;
      return data;
    }
  } catch (e) {
    console.warn(`Could not fetch PO details for ${poId}:`, e);
  }
  return null;
}

async function renderDecisionResult(result) {
  if (!result) return;
  if (result.detail || result.error) {
    console.error('API Error in decision payload:', result);
    alert(result.detail || result.error || 'Failed to retrieve invoice analysis.');
    return;
  }
  if (!result.decision && !result.extracted) {
    console.warn('Incomplete invoice payload received:', result);
    return;
  }
  currentResult = result;
  if (result.invoice_id) {
    currentInvoiceId = result.invoice_id;
  }

  setDisplay('empty-dashboard', false);
  setDisplay('result-dashboard', true);

  // Decision Banner Styling
  const banner = $('decision-banner');
  if (banner) {
    banner.className = 'decision-banner';
    if (result.decision === 'APPROVED') {
      banner.classList.add('status-approved');
    } else if (result.decision === 'REJECTED') {
      banner.classList.add('status-rejected');
    } else {
      banner.classList.add('status-review');
    }
  }

  const decBadge = $('decision-badge');
  if (decBadge) {
    decBadge.textContent = result.decision || 'UNKNOWN';
    if (result.decision === 'APPROVED') {
      decBadge.className = 'inline-flex items-center px-2 py-0.5 text-[11px] font-bold tracking-wide bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 font-mono';
    } else if (result.decision === 'REJECTED') {
      decBadge.className = 'inline-flex items-center px-2 py-0.5 text-[11px] font-bold tracking-wide bg-red-500/10 text-red-400 border border-red-500/30 font-mono';
    } else {
      decBadge.className = 'inline-flex items-center px-2 py-0.5 text-[11px] font-bold tracking-wide bg-amber-500/10 text-amber-400 border border-amber-500/30 font-mono';
    }
  }

  setText('reason-code-badge', result.reason_code || 'OK');
  setText('decision-summary', result.summary || '');

  // Confidence Widget with 3-tier colors
  const confVal = typeof result.confidence === 'number' ? result.confidence : 0;
  const confTier = getConfidenceTier(confVal);
  setText('confidence-val', confVal.toFixed(2));

  const tierPill = $('confidence-tier-pill');
  if (tierPill) {
    tierPill.textContent = `${confTier.label} (${Math.round(confVal * 100)}%)`;
    if (confTier.tier === 'green') {
      tierPill.className = 'inline-flex items-center px-1.5 py-0.2 text-[10px] font-bold font-mono bg-emerald-500/10 text-emerald-400 border border-emerald-500/30';
    } else if (confTier.tier === 'red') {
      tierPill.className = 'inline-flex items-center px-1.5 py-0.2 text-[10px] font-bold font-mono bg-red-500/10 text-red-400 border border-red-500/30';
    } else {
      tierPill.className = 'inline-flex items-center px-1.5 py-0.2 text-[10px] font-bold font-mono bg-amber-500/10 text-amber-400 border border-amber-500/30';
    }
  }

  const barFill = $('confidence-bar-fill');
  if (barFill) {
    barFill.style.width = `${Math.min(100, Math.max(0, confVal * 100))}%`;
    barFill.style.backgroundColor = confTier.barColor;
  }

  // Active PO Determination & Rejected Case Handling
  const isRejected = result.decision === 'REJECTED';
  const candidates = result.match?.candidates || [];
  const poNotice = $('rejected-po-notice');
  const poComparisonContainer = $('po-comparison-container');
  const toggleBtn = $('btn-toggle-suspected-candidates');
  const toggleBtnText = $('toggle-candidates-btn-text');
  const countPill = $('suspected-candidates-count-pill');
  const noticeDesc = $('rejected-notice-desc');

  if (isRejected) {
    if (poNotice) poNotice.classList.remove('hidden');
    if (poComparisonContainer) poComparisonContainer.classList.add('hidden');

    if (countPill) countPill.textContent = candidates.length;
    if (toggleBtnText) toggleBtnText.textContent = 'View Suspected Candidates';

    if (candidates.length === 0) {
      if (toggleBtn) toggleBtn.style.display = 'none';
      if (noticeDesc) {
        noticeDesc.textContent = 'This invoice was rejected as no purchase orders were matched. PO comparison is not applicable.';
      }
    } else {
      if (toggleBtn) {
        toggleBtn.style.display = 'inline-flex';
        toggleBtn.onclick = async () => {
          if (!poComparisonContainer) return;
          const isHidden = poComparisonContainer.classList.contains('hidden');
          if (isHidden) {
            poComparisonContainer.classList.remove('hidden');
            if (toggleBtnText) toggleBtnText.textContent = 'Hide Suspected Candidates';
            if (!activePOId && candidates.length > 0) {
              activePOId = candidates[0].po_id;
              const d = await fetchPODetail(activePOId);
              renderPOSelectorToolbar(result, activePOId);
              renderSideBySide(result, activePOId, d);
              renderCandidateTable(candidates, activePOId);
            }
          } else {
            poComparisonContainer.classList.add('hidden');
            if (toggleBtnText) toggleBtnText.textContent = 'View Suspected Candidates';
          }
        };
      }
      if (noticeDesc) {
        noticeDesc.textContent = `This invoice was rejected and does not belong to any purchase order (${candidates.length} open candidate PO${candidates.length > 1 ? 's were' : ' was'} evaluated). PO comparisons are hidden by default.`;
      }
    }

    activePOId = null;
  } else {
    if (poNotice) poNotice.classList.add('hidden');
    if (poComparisonContainer) poComparisonContainer.classList.remove('hidden');
    activePOId = result.match?.selected_po || (result.match?.candidates?.[0]?.po_id ?? null);
  }

  // Prominent PO Selector Toolbar
  renderPOSelectorToolbar(result, activePOId);

  // Review Actions Panel
  renderReviewPanel(result.review);

  // Snapshot Bar
  renderSnapshotBar(result, activePOId);

  // Load PO Detail & Render Side-by-Side Verification
  let poDetail = null;
  if (activePOId) {
    poDetail = await fetchPODetail(activePOId);
  }
  const invCurr = result.extracted?.currency?.value || 'INR';
  const poCurr = poDetail?.po?.currency || result.po_balance?.currency || 'INR';
  renderSideBySide(result, activePOId, poDetail);

  // PO Balance Consumption Card
  renderBalanceCard(result.po_balance, poCurr, invCurr);

  // Candidate POs Ranking
  renderCandidateTable(result.match?.candidates || [], activePOId);

  // Extracted Fields Table
  renderExtractedFields(result.extracted);

  // Auditable Reasoning Cards
  renderReasoning(result.reasoning || []);

  // Validation Rules Table with Filters
  renderRules(result.checks || [], activeRuleFilter);

  // Execution Trace
  renderTrace(result.trace || [], result.timings_ms);

  // Legacy fallbacks
  setHtml('line-items-body', '');
  setHtml('paired-lines-body', '');
  setHtml('po-match-info', '');
  setText('balance-legend', '');
}

function renderPOSelectorToolbar(result, currentActivePO) {
  const toolbar = $('po-selector-toolbar');
  const pillsContainer = $('po-selector-pills');
  const countBadge = $('candidate-count-badge');
  if (!toolbar || !pillsContainer) return;

  const candidates = result.match?.candidates || [];
  if (candidates.length <= 1 && result.decision === 'APPROVED') {
    toolbar.classList.add('hidden');
    return;
  }

  if (candidates.length === 0 && !currentActivePO) {
    toolbar.classList.add('hidden');
    return;
  }

  toolbar.classList.remove('hidden');
  if (countBadge) {
    countBadge.textContent = `${candidates.length} Candidate${candidates.length > 1 ? 's' : ''} Available`;
  }

  pillsContainer.innerHTML = '';
  candidates.forEach((c, idx) => {
    const isActive = c.po_id === currentActivePO;
    const scorePct = Math.round((Number(c.score) || 0) * 100);
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = `po-pill-btn ${isActive ? 'active' : ''}`;
    btn.innerHTML = `
      <span>${isActive ? '●' : '○'}</span>
      <strong>${escapeHtml(c.po_id)}</strong>
      <span class="po-pill-tag">${idx === 0 ? 'Top Match · ' : ''}${scorePct}% Fit</span>
    `;

    btn.addEventListener('click', async () => {
      await switchActivePO(c.po_id);
    });

    pillsContainer.appendChild(btn);
  });
}

async function switchActivePO(poId) {
  activePOId = poId;
  const poDetail = await fetchPODetail(poId);
  renderPOSelectorToolbar(currentResult, activePOId);
  renderSnapshotBar(currentResult, activePOId);
  renderSideBySide(currentResult, activePOId, poDetail);
  renderCandidateTable(currentResult.match?.candidates || [], activePOId);

  // Synchronize with reviewer form radio button
  const targetRadio = document.querySelector(`input[name="select_po_opt"][value="${poId}"]`);
  if (targetRadio) targetRadio.checked = true;
}

function renderReviewPanel(review) {
  const reviewPanel = $('review-action-panel');
  const reviewControls = $('review-action-controls');
  if (reviewControls) reviewControls.innerHTML = '';

  if (review && review.required) {
    if (reviewPanel) reviewPanel.classList.remove('hidden');
    (review.actions || []).forEach(action => {
      if (action.type === 'select_po' && reviewControls) {
        const div = document.createElement('div');
        div.innerHTML = `<strong style="display:block; margin-bottom: 6px; font-size: 0.82rem;">Select Purchase Order to Approve:</strong> `;
        const optsContainer = document.createElement('div');
        optsContainer.style.display = 'flex';
        optsContainer.style.flexWrap = 'wrap';
        optsContainer.style.gap = '12px';

        action.options.forEach((po, idx) => {
          const isChecked = po === activePOId || idx === 0 ? 'checked' : '';
          optsContainer.innerHTML += `
            <label style="cursor: pointer; display: inline-flex; align-items: center; gap: 6px; font-size: 0.85rem; background: #f8fafc; padding: 4px 10px; border-radius: 6px; border: 1px solid #e2e8f0;">
              <input type="radio" name="select_po_opt" value="${escapeHtml(po)}" ${isChecked}>
              <strong>${escapeHtml(po)}</strong>
            </label>
          `;
        });
        div.appendChild(optsContainer);
        reviewControls.appendChild(div);
      }
    });
  } else {
    if (reviewPanel) reviewPanel.classList.add('hidden');
  }
}

function renderSnapshotBar(result, currentPoId) {
  const ext = result.extracted || {};
  const curr = ext.currency?.value || 'INR';

  setText('snap-inv-no', ext.invoice_number?.value || 'N/A');
  setText('snap-vendor', ext.vendor?.name || 'Unknown Vendor');
  setText('snap-date', ext.invoice_date?.value || '—');

  const totalVal = ext.grand_total?.value != null ? Number(ext.grand_total.value).toFixed(2) : '0.00';
  setText('snap-total', `${curr} ${Number(totalVal).toLocaleString()}`);

  const poEl = $('snap-po');
  if (poEl) {
    const candidates = result.match?.candidates || [];
    if (result.decision === 'APPROVED') {
      poEl.textContent = `MATCHED: ${currentPoId || result.match?.selected_po || 'APPROVED'}`;
      poEl.className = 'inline-flex items-center px-1.5 py-0.5 text-[10px] font-bold font-mono bg-emerald-500/10 text-emerald-400 border border-emerald-500/30';
    } else if (result.decision === 'REJECTED') {
      poEl.textContent = 'STATUS: REJECTED';
      poEl.className = 'inline-flex items-center px-1.5 py-0.5 text-[10px] font-bold font-mono bg-red-500/10 text-red-400 border border-red-500/30';
    } else {
      if (candidates.length > 1) {
        poEl.textContent = `REVIEWING: ${currentPoId || 'CANDIDATE'} (${candidates.length} CANDIDATES)`;
        poEl.className = 'inline-flex items-center px-1.5 py-0.5 text-[10px] font-bold font-mono bg-amber-500/10 text-amber-400 border border-amber-500/30';
      } else if (currentPoId) {
        poEl.textContent = `CANDIDATE: ${currentPoId}`;
        poEl.className = 'inline-flex items-center px-1.5 py-0.5 text-[10px] font-bold font-mono bg-blue-500/10 text-blue-400 border border-blue-500/30';
      } else {
        poEl.textContent = 'NO PO MATCHED';
        poEl.className = 'inline-flex items-center px-1.5 py-0.5 text-[10px] font-bold font-mono bg-[#1a2434] text-[#94a3b8] border border-[#232f42]';
      }
    }
  }

  const btnViewDoc = $('btn-snap-view-doc');
  if (btnViewDoc) {
    btnViewDoc.onclick = () => {
      openDocumentViewer({
        invoiceId: currentInvoiceId || result.invoice_id,
        invoiceNo: ext.invoice_number?.value || result.invoice_no,
        vendorName: ext.vendor?.name || result.vendor_name || result.vendor_id,
        fileName: result.file_name || ext.source?.file_name,
        filePath: result.file_path,
      });
    };
  }
}

function renderSideBySide(result, targetPoId, poDetail) {
  const ext = result.extracted || {};
  setText('active-po-label', targetPoId || 'None Selected');
  setText('reconcile-po-id', targetPoId ? `PO: ${targetPoId}` : 'No Active PO');

  const invCurr = ext.currency?.value || 'INR';
  const poCurr = poDetail?.po?.currency || result.po_balance?.currency || 'INR';
  const isCurrencyMismatch = Boolean(targetPoId && invCurr && poCurr && invCurr.toUpperCase() !== poCurr.toUpperCase());

  const invVendor = ext.vendor?.name || '—';
  const invGstin = ext.vendor?.gstin || 'Not Provided';
  const invTotal = ext.grand_total?.value != null ? Number(ext.grand_total.value) : 0;
  const invDate = ext.invoice_date?.value || '—';

  // Find candidate matching info for active PO
  const candidate = (result.match?.candidates || []).find(c => c.po_id === targetPoId);

  // 1. Vendor Alignment
  const poVendor = poDetail?.vendor?.name || poDetail?.po?.vendor_id || (targetPoId ? 'Catalog Master' : '—');
  const poGstin = poDetail?.vendor?.gstin || '—';
  const invBank = ext.vendor?.bank_account || '—';
  const poBank = poDetail?.vendor?.bank_account || '—';

  setText('diff-inv-vendor', invVendor);
  setText('diff-inv-gstin', invGstin !== 'Not Provided' ? `GSTIN: ${invGstin}` : 'GSTIN: Not Available');
  setText('diff-po-vendor', poVendor);
  setText('diff-po-gstin', poGstin !== '—' ? `GSTIN: ${poGstin}` : 'GSTIN: Not Recorded');

  const cleanInvBank = invBank !== '—' ? invBank.replace(/[^a-zA-Z0-9]/g, '').toUpperCase() : '';
  const cleanPoBank = poBank !== '—' ? poBank.replace(/[^a-zA-Z0-9]/g, '').toUpperCase() : '';
  const isBankMismatch = Boolean(targetPoId && cleanInvBank && cleanPoBank && cleanInvBank !== cleanPoBank);

  const invBankEl = $('diff-inv-bank');
  if (invBankEl) {
    if (invBank !== '—') {
      invBankEl.textContent = `Bank A/C: ${invBank}`;
      invBankEl.className = isBankMismatch 
        ? 'text-[11px] text-amber-400 font-mono mt-0.5' 
        : 'text-[11px] text-[#94a3b8] font-mono mt-0.5';
    } else {
      invBankEl.textContent = 'Bank A/C: Not On Document';
      invBankEl.className = 'text-[11px] text-[#64748b] font-mono mt-0.5';
    }
  }

  const poBankEl = $('diff-po-bank');
  if (poBankEl) {
    if (poBank !== '—') {
      poBankEl.textContent = `Bank A/C: ${poBank}`;
      poBankEl.className = isBankMismatch 
        ? 'text-[11px] text-red-400 font-mono mt-0.5' 
        : 'text-[11px] text-[#94a3b8] font-mono mt-0.5';
    } else {
      poBankEl.textContent = targetPoId ? 'Bank A/C: Not Recorded In Master' : 'Bank A/C: —';
      poBankEl.className = 'text-[11px] text-[#64748b] font-mono mt-0.5';
    }
  }

  const vStatus = $('diff-vendor-status');
  const vSub = $('diff-vendor-sub');
  if (vStatus) {
    if (!targetPoId) {
      vStatus.className = 'diff-status-pill status-neutral';
      vStatus.textContent = 'NO PO LINKED';
      if (vSub) vSub.textContent = 'Select a purchase order to verify vendor';
    } else if (isBankMismatch) {
      vStatus.className = 'diff-status-pill status-mismatch';
      vStatus.textContent = 'BANK ACCOUNT MISMATCH';
      if (vSub) vSub.textContent = `Invoice bank A/C (${invBank}) differs from ERP master record (${poBank})`;
    } else if (poGstin !== '—' && invGstin !== 'Not Provided' && invGstin.toUpperCase() === poGstin.toUpperCase()) {
      vStatus.className = 'diff-status-pill status-match';
      vStatus.textContent = cleanInvBank && cleanPoBank ? 'EXACT GSTIN & BANK MATCH' : 'EXACT GSTIN MATCH';
      if (vSub) vSub.textContent = cleanInvBank && cleanPoBank
        ? 'Tax ID, vendor entity, and bank account verified with master record'
        : 'Tax ID and vendor entity verified with master record';
    } else if (poVendor.toLowerCase().includes(invVendor.toLowerCase()) || invVendor.toLowerCase().includes(poVendor.toLowerCase())) {
      vStatus.className = 'diff-status-pill status-match';
      vStatus.textContent = 'VENDOR RECOGNIZED';
      if (vSub) vSub.textContent = 'Entity matched via master database record / alias';
    } else {
      vStatus.className = 'diff-status-pill status-drift';
      vStatus.textContent = 'ENTITY VARIANCE';
      if (vSub) vSub.textContent = 'Resolved via trading alias; manual check recommended';
    }
  }

  // 2. Chronology / Dates
  const poDate = poDetail?.po?.po_date || '—';
  setText('diff-inv-date', invDate);
  setText('diff-po-date', poDate !== '—' ? poDate : 'Not Specified');

  const dStatus = $('diff-date-status');
  const dSub = $('diff-date-sub');
  if (dStatus) {
    if (invDate !== '—' && poDate !== '—') {
      if (invDate >= poDate) {
        dStatus.className = 'diff-status-pill status-match';
        dStatus.textContent = 'CHRONOLOGY VALID';
        if (dSub) dSub.textContent = 'Invoice is dated on or after purchase order issuance';
      } else {
        dStatus.className = 'diff-status-pill status-mismatch';
        dStatus.textContent = 'DATE ANOMALY';
        if (dSub) dSub.textContent = 'Invoice date pre-dates purchase order creation date';
      }
    } else {
      dStatus.className = 'diff-status-pill status-neutral';
      dStatus.textContent = 'DATE PENDING';
      if (dSub) dSub.textContent = 'Timeline verification awaiting PO confirmation';
    }
  }

  // 3. Order Value & Coverage Alignment (With Currency Separation)
  const poTotal = poDetail?.po?.total != null ? Number(poDetail.po.total) : null;
  setText('diff-inv-total', `${invCurr} ${invTotal.toLocaleString(undefined, { minimumFractionDigits: 2 })}`);
  setText('diff-po-total', poTotal != null ? `${poCurr} ${poTotal.toLocaleString(undefined, { minimumFractionDigits: 2 })}` : '—');

  const invTotalSub = $('diff-inv-total-sub');
  const poTotalSub = $('diff-po-total-sub');
  const tStatus = $('diff-total-status');
  const tSub = $('diff-total-sub');
  const barContainer = $('diff-coverage-bar-container');
  const barFill = $('diff-coverage-bar-fill');

  if (poTotal != null && poTotal > 0) {
    if (barContainer) barContainer.classList.remove('hidden');

    if (isCurrencyMismatch) {
      if (invTotalSub) invTotalSub.textContent = `Current Invoice Claim (${invCurr})`;
      if (poTotalSub) poTotalSub.textContent = `Total PO Commitment (${poCurr} ${poTotal.toLocaleString(undefined, { minimumFractionDigits: 2 })})`;
      if (tStatus) {
        tStatus.className = 'diff-status-pill status-mismatch';
        tStatus.textContent = `CURRENCY MISMATCH · ${invCurr} vs ${poCurr}`;
      }
      if (barFill) {
        barFill.style.width = '100%';
        barFill.className = 'recon-progress-fill fill-red';
      }
      if (tSub) {
        tSub.textContent = `Invoice currency (${invCurr}) does not match Purchase Order currency (${poCurr}). Direct numerical reconciliation is blocked without foreign exchange conversion.`;
      }
    } else {
      const diff = invTotal - poTotal;
      const billedPct = (invTotal / poTotal) * 100;
      const remainingAfter = poTotal - invTotal;

      if (Math.abs(diff) < 0.01) {
        if (invTotalSub) invTotalSub.textContent = 'Current Claim (Full Settlement)';
        if (poTotalSub) poTotalSub.textContent = 'Total PO Commitment (100% matched)';
        if (tStatus) {
          tStatus.className = 'diff-status-pill status-match';
          tStatus.textContent = 'FULL PO FULFILLMENT · 100%';
        }
        if (barFill) {
          barFill.style.width = '100%';
          barFill.className = 'recon-progress-fill fill-green';
        }
        if (tSub) tSub.textContent = `Invoice completes 100% of the total PO commitment (${invCurr} ${poTotal.toLocaleString(undefined, { minimumFractionDigits: 2 })}).`;
      } else if (diff < 0) {
        if (invTotalSub) invTotalSub.textContent = `Current Invoice Claim (Partial · ${billedPct.toFixed(0)}%)`;
        if (poTotalSub) poTotalSub.textContent = `Total PO Lifetime Commitment (${invCurr} ${remainingAfter.toLocaleString(undefined, { minimumFractionDigits: 2 })} remaining)`;
        if (tStatus) {
          tStatus.className = 'diff-status-pill status-partial';
          tStatus.textContent = `PARTIAL BILLING · ${billedPct.toFixed(0)}% COVERAGE`;
        }
        if (barFill) {
          barFill.style.width = `${Math.min(100, Math.max(0, billedPct))}%`;
          barFill.className = 'recon-progress-fill';
        }
        if (tSub) tSub.textContent = `Covers ${billedPct.toFixed(0)}% of PO allocation. Normal partial milestone with ${invCurr} ${remainingAfter.toLocaleString(undefined, { minimumFractionDigits: 2 })} remaining headroom.`;
      } else {
        const overrunPct = ((diff / poTotal) * 100).toFixed(1);
        if (invTotalSub) invTotalSub.textContent = 'Current Claim (Exceeds PO Allocation)';
        if (poTotalSub) poTotalSub.textContent = `Total PO Commitment (Deficit: -${invCurr} ${diff.toFixed(2)})`;
        if (tStatus) {
          tStatus.className = 'diff-status-pill status-drift';
          tStatus.textContent = `BUDGET OVERRUN · +${overrunPct}%`;
        }
        if (barFill) {
          barFill.style.width = '100%';
          barFill.className = 'recon-progress-fill fill-red';
        }
        if (tSub) tSub.textContent = `Exceeds total PO allocation by +${invCurr} ${diff.toLocaleString(undefined, { minimumFractionDigits: 2 })} (${overrunPct}% overrun).`;
      }
    }
  } else {
    if (barContainer) barContainer.classList.add('hidden');
    if (invTotalSub) invTotalSub.textContent = 'Current Invoice Claim';
    if (poTotalSub) poTotalSub.textContent = targetPoId ? 'PO Commitment Not Specified' : 'No Purchase Order Selected';
    if (tStatus) {
      tStatus.className = 'diff-status-pill status-neutral';
      tStatus.textContent = targetPoId ? 'PO VALUE PENDING' : 'NO PO LINKED';
    }
    if (tSub) tSub.textContent = targetPoId ? 'PO total not found in database records' : 'Select a purchase order to verify commitment amount';
  }

  // 4. Line Items Comparison Widgets (Paired Two-Row Layout per Item with Accordion)
  const widgetsContainer = $('line-items-widgets-container');
  if (!widgetsContainer) return;
  widgetsContainer.innerHTML = '';

  const invLines = ext.line_items || [];
  const poItems = poDetail?.items || [];
  const lineMatches = candidate?.line_matches || [];

  const controlsEl = $('items-accordion-controls');
  if (controlsEl) {
    controlsEl.style.display = invLines.length > 0 ? 'flex' : 'none';
  }
  setupItemAccordionControls();

  if (invLines.length === 0) {
    widgetsContainer.innerHTML = '<div class="empty-state">No line items extracted from document</div>';
    return;
  }

  invLines.forEach((invLine, idx) => {
    const matchDetail = lineMatches.find(m => m.invoice_line_no === (invLine.line_no ?? (idx + 1)))
      || lineMatches[idx];

    let poItem = null;
    if (matchDetail && matchDetail.po_item_row_id) {
      poItem = poItems.find(p => p.row_id === matchDetail.po_item_row_id);
    }
    if (!poItem && matchDetail && matchDetail.po_item_name) {
      poItem = poItems.find(p => p.item_name === matchDetail.po_item_name);
    }

    const pUnit = poItem ? Number(poItem.unit_price) : null;
    const iUnit = invLine.unit_price != null ? Number(invLine.unit_price) : null;
    const pQty = poItem ? Number(poItem.qty_ordered) : null;
    const iQty = invLine.quantity != null ? Number(invLine.quantity) : null;
    const iTot = invLine.line_total != null ? Number(invLine.line_total) : 0;
    const pTot = (pUnit != null && pQty != null) ? pUnit * pQty : null;

    let overallBadgeHtml = '';
    const deltaChips = [];

    if (!targetPoId) {
      overallBadgeHtml = '<span class="item-match-badge diff-unmatched">NO PO LINKED</span>';
    } else if (!poItem && (!matchDetail || matchDetail.match_method === 'none')) {
      overallBadgeHtml = '<span class="item-match-badge diff-unmatched">UNMATCHED LINE</span>';
      deltaChips.push('<span class="delta-chip delta-drift">Item not present in purchase order</span>');
    } else {
      if (isCurrencyMismatch) {
        overallBadgeHtml = `<span class="item-match-badge diff-drift">CURRENCY MISMATCH (${invCurr} vs ${poCurr})</span>`;
        deltaChips.push(`<span class="delta-chip delta-warn">DENOMINATION: ${invCurr} (Invoice) vs ${poCurr} (PO)</span>`);
        if (pUnit != null && iUnit != null) {
          if (Math.abs(iUnit - pUnit) <= 0.01) {
            deltaChips.push(`<span class="delta-chip delta-info">NUMERICAL VALUE: ${iUnit.toFixed(2)} (Identical number under different currencies)</span>`);
          } else {
            deltaChips.push(`<span class="delta-chip delta-drift">NUMERICAL VALUE: ${invCurr} ${iUnit.toFixed(2)} vs ${poCurr} ${pUnit.toFixed(2)}</span>`);
          }
        }
      } else {
        // Analyze price diff
        let isPriceMatch = true;
        let priceDiff = 0;
        if (pUnit != null && iUnit != null) {
          priceDiff = iUnit - pUnit;
          isPriceMatch = Math.abs(priceDiff) <= 0.01;
        }

        // Analyze qty diff
        let isQtyMatch = true;
        let qtyDiff = 0;
        if (pQty != null && iQty != null) {
          qtyDiff = iQty - pQty;
          isQtyMatch = Math.abs(qtyDiff) <= 0.01;
        }

        if (isPriceMatch && isQtyMatch) {
          overallBadgeHtml = '<span class="item-match-badge diff-exact">MATCH: EXACT PRICE & QTY</span>';
          deltaChips.push('<span class="delta-chip delta-ok">RATE: EXACT MATCH</span>');
          deltaChips.push('<span class="delta-chip delta-ok">QTY: ALLOCATED HEADROOM VALID</span>');
        } else if (!isPriceMatch && !isQtyMatch) {
          overallBadgeHtml = '<span class="item-match-badge diff-drift">VARIANCE: RATE & QUANTITY</span>';
        } else if (!isPriceMatch) {
          overallBadgeHtml = '<span class="item-match-badge diff-drift">VARIANCE: UNIT RATE</span>';
        } else {
          overallBadgeHtml = '<span class="item-match-badge diff-drift">VARIANCE: QUANTITY</span>';
        }

        if (!isPriceMatch && pUnit != null && iUnit != null) {
          const driftPct = ((priceDiff / pUnit) * 100).toFixed(1);
          const sign = priceDiff > 0 ? '+' : '';
          const chipClass = priceDiff > 0 ? 'delta-drift' : 'delta-info';
          deltaChips.push(`<span class="delta-chip ${chipClass}">RATE VARIANCE: ${sign}${invCurr} ${priceDiff.toFixed(2)} (${sign}${driftPct}%)</span>`);
        }

        if (!isQtyMatch && pQty != null && iQty != null) {
          const sign = qtyDiff > 0 ? '+' : '';
          const chipClass = qtyDiff > 0 ? 'delta-warn' : 'delta-ok';
          deltaChips.push(`<span class="delta-chip ${chipClass}">QTY VARIANCE: ${sign}${qtyDiff} ${invLine.uom || 'units'} vs PO</span>`);
        }

        if (pTot != null) {
          const totDiff = iTot - pTot;
          if (Math.abs(totDiff) > 0.01) {
            const sign = totDiff > 0 ? '+' : '';
            deltaChips.push(`<span class="delta-chip delta-warn">LINE TOTAL DELTA: ${sign}${invCurr} ${totDiff.toFixed(2)}</span>`);
          }
        }
      }
    }

    const widget = document.createElement('div');
    widget.className = 'item-widget';
    widget.innerHTML = `
      <div class="item-widget-header" role="button" tabindex="0" aria-expanded="false" title="Click to view PO comparison details">
        <div class="item-widget-header-left">
          <span class="item-line-no">Item #${invLine.line_no ?? (idx + 1)}</span>
          <span class="item-main-desc" title="${escapeHtml(invLine.description)}">${escapeHtml(invLine.description)}</span>
        </div>
        <div class="item-widget-header-right">
          <div class="item-header-meta">
            <span class="meta-qty">${invLine.quantity != null ? `${invLine.quantity} ${escapeHtml(invLine.uom || '')}` : '—'}</span>
            <span class="meta-dot">·</span>
            <span class="meta-rate">${invCurr} ${(invLine.unit_price ?? 0).toFixed(2)}</span>
            <span class="meta-dot">·</span>
            <span class="meta-total">${invCurr} ${iTot.toFixed(2)}</span>
          </div>
          ${overallBadgeHtml}
          <svg class="item-widget-chevron w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
          </svg>
        </div>
      </div>

      <div class="item-widget-body">
        <div class="item-widget-grid">
          <!-- Row 1: Invoice Claim -->
          <div class="item-row item-row-invoice">
            <div><span class="badge-source badge-inv">INVOICE (${invCurr})</span></div>
            <div class="item-cell-desc">
              ${escapeHtml(invLine.description)}
            </div>
            <div class="item-cell-stat">
              <span class="stat-lbl">Billed Qty</span>
              <span class="stat-val">${invLine.quantity ?? '—'} ${escapeHtml(invLine.uom || '')}</span>
            </div>
            <div class="item-cell-stat">
              <span class="stat-lbl">Invoice Rate</span>
              <span class="stat-val">${invCurr} ${(invLine.unit_price ?? 0).toFixed(2)}</span>
            </div>
            <div class="item-cell-stat stat-total">
              <span class="stat-lbl">Invoice Total</span>
              <span class="stat-val">${invCurr} ${iTot.toFixed(2)}</span>
            </div>
          </div>

          <!-- Row 2: Matched PO Specification -->
          <div class="item-row item-row-po">
            <div><span class="badge-source badge-po">PO MASTER (${poCurr})</span></div>
            <div class="item-cell-desc">
              ${poItem ? `
                <div>${escapeHtml(poItem.item_name)}</div>
                ${poItem.description ? `<div class="subtext">${escapeHtml(poItem.description)}</div>` : ''}
              ` : (matchDetail?.po_item_name ? `<div>${escapeHtml(matchDetail.po_item_name)}</div>` : '<span class="hint">No corresponding PO item</span>')}
            </div>
            <div class="item-cell-stat">
              <span class="stat-lbl">PO Ordered</span>
              <span class="stat-val">${poItem ? `${poItem.qty_ordered} ${escapeHtml(poItem.uom || '')}` : '—'} ${poItem ? `<span class="rem-note">(${poItem.qty_remaining} rem)</span>` : ''}</span>
            </div>
            <div class="item-cell-stat">
              <span class="stat-lbl">PO Rate</span>
              <span class="stat-val">${poItem ? `${poCurr} ${Number(poItem.unit_price).toFixed(2)}` : '—'}</span>
            </div>
            <div class="item-cell-stat stat-total">
              <span class="stat-lbl">PO Line Total</span>
              <span class="stat-val">${pTot != null ? `${poCurr} ${pTot.toFixed(2)}` : '—'}</span>
            </div>
          </div>
        </div>

        ${deltaChips.length > 0 ? `
          <div class="item-delta-strip">
            ${deltaChips.join('')}
          </div>
        ` : ''}
      </div>
    `;

    const header = widget.querySelector('.item-widget-header');
    if (header) {
      const toggle = () => {
        const isOpen = widget.classList.toggle('is-open');
        header.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
      };
      header.addEventListener('click', toggle);
      header.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          toggle();
        }
      });
    }

    widgetsContainer.appendChild(widget);
  });
}

function setupItemAccordionControls() {
  const btnExpand = $('btn-expand-all-items');
  const btnCollapse = $('btn-collapse-all-items');

  if (btnExpand && !btnExpand._bound) {
    btnExpand._bound = true;
    btnExpand.addEventListener('click', () => {
      document.querySelectorAll('#line-items-widgets-container .item-widget').forEach(w => {
        w.classList.add('is-open');
        w.querySelector('.item-widget-header')?.setAttribute('aria-expanded', 'true');
      });
    });
  }

  if (btnCollapse && !btnCollapse._bound) {
    btnCollapse._bound = true;
    btnCollapse.addEventListener('click', () => {
      document.querySelectorAll('#line-items-widgets-container .item-widget').forEach(w => {
        w.classList.remove('is-open');
        w.querySelector('.item-widget-header')?.setAttribute('aria-expanded', 'false');
      });
    });
  }
}

function renderBalanceCard(bal, poCurr = 'INR', invCurr = null) {
  const card = $('po-balance-card');
  if (!card) return;
  if (!bal) {
    card.classList.add('hidden');
    return;
  }
  card.classList.remove('hidden');

  const curr = poCurr || bal.currency || 'INR';
  const total = Number(bal.po_total) || 0;
  const billed = Number(bal.previously_billed) || 0;
  const thisInv = Number(bal.this_invoice) || 0;
  const remaining = Number(bal.remaining_after) || 0;

  const isCurrencyMismatch = Boolean(invCurr && curr && invCurr.toUpperCase() !== curr.toUpperCase());

  const billedPct = total > 0 ? (billed / total) * 100 : 0;
  const thisPct = total > 0 ? (thisInv / total) * 100 : 0;
  const remPct = total > 0 ? Math.max(0, (remaining / total) * 100) : 0;

  setText('kpi-po-total', `${curr} ${total.toLocaleString(undefined, { minimumFractionDigits: 2 })}`);
  setText('kpi-po-billed', `${curr} ${billed.toLocaleString(undefined, { minimumFractionDigits: 2 })}`);
  setText('kpi-po-billed-pct', `${billedPct.toFixed(1)}% drawn previously`);

  if (isCurrencyMismatch) {
    setText('kpi-po-this', `${invCurr} ${thisInv.toLocaleString(undefined, { minimumFractionDigits: 2 })}`);
    setText('kpi-po-this-pct', `* Denominated in ${invCurr} (PO is in ${curr})`);
  } else {
    setText('kpi-po-this', `${curr} ${thisInv.toLocaleString(undefined, { minimumFractionDigits: 2 })}`);
    setText('kpi-po-this-pct', `${thisPct.toFixed(1)}% of total commitment`);
  }

  setText('kpi-po-rem', `${curr} ${remaining.toLocaleString(undefined, { minimumFractionDigits: 2 })}`);

  const remCard = $('kpi-remaining-card');
  const remStatusEl = $('kpi-po-rem-status');
  const healthPill = $('balance-health-pill');

  if (remCard) {
    remCard.className = 'balance-kpi-card highlight-remaining';
    if (isCurrencyMismatch) {
      remCard.classList.add('over');
      if (remStatusEl) remStatusEl.textContent = `Currency Mismatch: Invoice ${invCurr} vs PO ${curr}`;
      if (healthPill) {
        healthPill.className = 'badge-po-target';
        healthPill.style.background = '#fee2e2';
        healthPill.style.color = '#b91c1c';
        healthPill.style.borderColor = '#fca5a5';
        healthPill.textContent = 'CURRENCY MISMATCH';
      }
    } else if (remaining < 0) {
      remCard.classList.add('over');
      if (remStatusEl) remStatusEl.textContent = `Deficit: ${curr} ${Math.abs(remaining).toFixed(2)} over commitment`;
      if (healthPill) {
        healthPill.className = 'badge-po-target';
        healthPill.style.background = '#fee2e2';
        healthPill.style.color = '#b91c1c';
        healthPill.style.borderColor = '#fca5a5';
        healthPill.textContent = 'BUDGET EXCEEDED';
      }
    } else if (remaining < total * 0.15) {
      remCard.classList.add('tight');
      if (remStatusEl) remStatusEl.textContent = 'Caution: Under 15% headroom remaining';
      if (healthPill) {
        healthPill.className = 'badge-po-target';
        healthPill.style.background = '#fef3c7';
        healthPill.style.color = '#b45309';
        healthPill.style.borderColor = '#fde68a';
        healthPill.textContent = 'LOW HEADROOM';
      }
    } else {
      if (remStatusEl) remStatusEl.textContent = `${remPct.toFixed(1)}% headroom remaining`;
      if (healthPill) {
        healthPill.className = 'badge-po-target';
        healthPill.style.background = '#dcfce7';
        healthPill.style.color = '#15803d';
        healthPill.style.borderColor = '#86efac';
        healthPill.textContent = 'HEALTHY ALLOCATION';
      }
    }
  }

  // Multi-segment Bar Fill
  const barConsumed = $('balance-bar-consumed');
  if (barConsumed) barConsumed.style.width = `${Math.min(100, billedPct)}%`;

  const barThis = $('balance-bar-this');
  if (barThis) barThis.style.width = `${Math.min(100 - billedPct, thisPct)}%`;

  const barRem = $('balance-bar-remaining');
  if (barRem) barRem.style.width = `${Math.max(0, remPct)}%`;

  const overageBar = $('balance-bar-overage');
  const overageChip = $('leg-overage-chip');
  if (remaining < 0) {
    const overPct = Math.min(40, (Math.abs(remaining) / total) * 100);
    if (overageBar) {
      overageBar.classList.remove('hidden');
      overageBar.style.width = `${overPct}%`;
    }
    if (overageChip) overageChip.classList.remove('hidden');
    setText('leg-overage-val', `${curr} ${Math.abs(remaining).toFixed(2)}`);
  } else {
    if (overageBar) overageBar.classList.add('hidden');
    if (overageChip) overageChip.classList.add('hidden');
  }

  setText('leg-billed-val', `${curr} ${billed.toFixed(2)}`);
  setText('leg-this-val', `${curr} ${thisInv.toFixed(2)}`);
  setText('leg-rem-val', `${curr} ${Math.max(0, remaining).toFixed(2)}`);
}

function parseNotePolarity(noteText) {
  const lower = String(noteText).toLowerCase();

  // Zero match or negation: e.g. "0/2", "0 of", "no match", "only 0"
  const isZeroMatch = /\b0\/\d+\b/.test(lower) || /\b0 of \d+\b/.test(lower) || lower.includes('no match') || lower.includes('unmatched') || lower.includes('only 0');

  // Overage or balance exhaustion: e.g. "consumes 113%", "consumes 108%", "exceeds"
  const isOverage = lower.includes('consumes 1') || lower.includes('exceed') || lower.includes('over') || lower.includes('deficit');

  // Danger:
  const isDanger = lower.includes('closed') || lower.includes('reject') || lower.includes('mismatch') || lower.includes('fail');

  // Warnings:
  const isWarning = isZeroMatch || isOverage || lower.includes('drift') || lower.includes('variance') || lower.includes('warn') || lower.includes('partial');

  // Positive:
  const isPositive = !isZeroMatch && !isOverage && !isDanger && (
    lower.includes('exact') || lower.includes('verified') || lower.includes('sufficient') || lower.includes('valid') || lower.includes('winner') || (lower.includes('match') && !lower.includes('drift'))
  );

  const isNormalConsumption = lower.includes('consumes') && !isOverage;

  if (isDanger) {
    return { pillClass: 'note-danger', label: 'REJECT' };
  } else if (isWarning) {
    return { pillClass: 'note-warning', label: 'CAUTION' };
  } else if (isPositive) {
    return { pillClass: 'note-positive', label: 'VERIFIED' };
  } else if (isNormalConsumption) {
    return { pillClass: 'note-positive', label: 'BUDGET OK' };
  } else {
    return { pillClass: 'note-info', label: 'NOTE' };
  }
}

function renderCandidateTable(candidates, selectedPoId) {
  const candBody = $('candidates-body');
  if (!candBody) return;
  candBody.innerHTML = '';

  if (!candidates || !candidates.length) {
    candBody.innerHTML = '<tr><td colspan="4" class="empty-state">No candidate purchase orders matched this document</td></tr>';
    return;
  }

  candidates.forEach(c => {
    const isSelected = c.po_id === selectedPoId;
    const scoreVal = Number(c.score) || 0;
    const scorePct = Math.round(scoreVal * 100);
    const scoreTier = getConfidenceTier(scoreVal);

    // Humanized Signals Calculations
    const sig = c.signals || {};
    const pPct = Math.round((sig.price ?? 0) * 100);
    const qPct = Math.round((sig.quantity ?? 0) * 100);
    const tPct = Math.round((sig.total_coverage ?? 0) * 100);
    const lPct = sig.line_coverage != null ? Math.round(sig.line_coverage * 100) : null;

    // Qualitative assessment
    let fitText = 'Moderate Fit';
    if (lPct === 100 && pPct === 100 && qPct === 100 && scorePct >= 75) {
      fitText = 'High Fit · 100% Price & line match (Partial draw)';
    } else if (scorePct >= 80) {
      fitText = 'High Fit · Strong contract alignment';
    } else if (scorePct >= 50) {
      fitText = 'Moderate Fit · Review item variations';
    } else if (scorePct >= 30) {
      fitText = 'Low Fit · Tight allocation or overrun';
    } else {
      fitText = 'Poor Fit · Unmatched catalog items';
    }

    const pClass = pPct >= 95 ? 'signal-green' : (pPct >= 80 ? 'signal-amber' : 'signal-red');
    const qClass = qPct >= 95 ? 'signal-green' : (qPct >= 80 ? 'signal-amber' : 'signal-red');

    // Total coverage / budget draw logic:
    // If invoice consumes balance normally (1% to 100%), it is a valid draw!
    // It is ONLY red if 0% or if overbilled (> 100%)
    let tClass = 'signal-blue';
    let tLabel = `Draw: ${tPct}%`;
    let tTitle = `Invoice draws ${tPct}% of the remaining PO balance (Normal partial delivery)`;
    if (tPct === 100) {
      tClass = 'signal-green';
      tLabel = 'Full PO (100%)';
      tTitle = 'Invoice consumes 100% of the remaining PO commitment';
    } else if (tPct > 100) {
      tClass = 'signal-red';
      tLabel = `Overrun: ${tPct}%`;
      tTitle = `Invoice exceeds remaining PO commitment by ${tPct - 100}%`;
    } else if (tPct === 0) {
      tClass = 'signal-red';
      tLabel = 'Draw: 0%';
      tTitle = 'Invoice does not cover any remaining PO balance';
    }

    let signalsHtml = `
      <div class="signal-chip-container">
        <span class="signal-chip ${pClass}" title="Price alignment between invoice and PO items">Price: ${pPct}%</span>
        <span class="signal-chip ${qClass}" title="Quantity alignment and remaining headroom">Qty: ${qPct}%</span>
        <span class="signal-chip ${tClass}" title="${escapeHtml(tTitle)}">${escapeHtml(tLabel)}</span>
        ${lPct != null ? `<span class="signal-chip signal-blue" title="Percentage of invoice lines matched">Lines: ${lPct}%</span>` : ''}
      </div>
    `;

    // Notes Parsing with Clean Polarity Labels (No emojis)
    const rawNotes = Array.isArray(c.notes) ? c.notes : (c.notes ? String(c.notes).split(';') : []);
    const cleanNotesList = [];
    rawNotes.forEach(n => {
      String(n).split(';').forEach(part => {
        const trimmed = part.trim();
        if (trimmed) cleanNotesList.push(trimmed);
      });
    });

    let notesHtml = '<div class="notes-pill-container">';
    if (cleanNotesList.length === 0) {
      notesHtml += '<span class="hint">Standard candidate score</span>';
    } else {
      cleanNotesList.forEach(noteText => {
        const { pillClass, label } = parseNotePolarity(noteText);
        notesHtml += `<span class="note-pill ${pillClass}"><strong>${label}:</strong> <span>${escapeHtml(noteText)}</span></span>`;
      });
    }
    notesHtml += '</div>';

    const tr = document.createElement('tr');
    tr.className = `hover:bg-[#1a2434]/60 transition cursor-pointer ${isSelected ? 'bg-amber-500/10 border-l-2 border-amber-500' : ''}`;
    tr.title = 'Click to preview side-by-side comparison for this PO';
    tr.innerHTML = `
      <td class="py-2.5 px-4">
        <span class="font-mono text-[13px] font-bold text-amber-400">${escapeHtml(c.po_id)}</span>
        ${isSelected ? '<span class="inline-flex items-center px-1.5 py-0.2 text-[9px] font-mono font-bold bg-amber-500 text-slate-950 ml-1">Selected</span>' : ''}
      </td>
      <td class="py-2.5 px-4">
        <div class="fit-pill">
          <span class="inline-flex px-1.5 py-0.5 text-[10px] font-mono font-bold ${scoreTier.tier === 'green' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30' : (scoreTier.tier === 'red' ? 'bg-red-500/10 text-red-400 border border-red-500/30' : 'bg-amber-500/10 text-amber-400 border border-amber-500/30')}">${scorePct}% Match</span>
          <span class="text-[10px] text-[#94a3b8] mt-0.5">${fitText}</span>
        </div>
      </td>
      <td class="py-2.5 px-4">${signalsHtml}</td>
      <td class="py-2.5 px-4">${notesHtml}</td>
    `;

    tr.addEventListener('click', async () => {
      await switchActivePO(c.po_id);
    });

    candBody.appendChild(tr);
  });
}

function renderExtractedFields(ext) {
  const fieldsBody = $('extracted-fields-body');
  if (!fieldsBody) return;
  fieldsBody.innerHTML = '';
  if (!ext) return;

  const addRow = (name, val, conf, isTotal) => {
    const tr = document.createElement('tr');
    tr.className = 'hover:bg-[#1a2434]/50 transition';
    let confHtml = '<span class="text-[#64748b]">—</span>';
    if (conf !== undefined && conf !== null) {
      const pct = (Number(conf) * 100).toFixed(0);
      confHtml = `<span class="inline-flex px-1.5 py-0.5 text-[10px] font-mono font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">${pct}%</span>`;
    }

    const valHtml = isTotal
      ? `<span class="font-mono font-bold text-amber-400 tabular-nums">${escapeHtml(String(val ?? '—'))}</span>`
      : `<span class="font-mono text-[#cbd5e1]">${escapeHtml(String(val ?? '—'))}</span>`;

    tr.innerHTML = `
      <td class="py-2.5 px-4 font-medium text-[#dee2ee]">${escapeHtml(name)}</td>
      <td class="py-2.5 px-4">${valHtml}</td>
      <td class="py-2.5 px-3 text-center">${confHtml}</td>
      <td class="py-2.5 px-4 text-right"><span class="font-bold text-emerald-400 text-[11px] font-mono">OK</span></td>
    `;
    fieldsBody.appendChild(tr);
  };

  addRow('Vendor Name', ext.vendor?.name, ext.vendor?.confidence, false);
  addRow('GSTIN', ext.vendor?.gstin, ext.vendor?.confidence, false);
  addRow('Bank Account', ext.vendor?.bank_account, ext.vendor?.confidence, false);
  addRow('Invoice #', ext.invoice_number?.value, ext.invoice_number?.confidence, false);
  addRow('Invoice Date', ext.invoice_date?.value, ext.invoice_date?.confidence, false);
  addRow('PO Reference', ext.po_reference?.value, ext.po_reference?.confidence, false);
  addRow('Currency', ext.currency?.value, ext.currency?.confidence, false);
  addRow('Total Invoiced', `${ext.currency?.value ?? 'INR'} ${ext.grand_total?.value != null ? Number(ext.grand_total.value).toLocaleString('en-IN') : 0}`, ext.grand_total?.confidence, true);
}

function renderReasoning(reasons) {
  const reasoningList = $('reasoning-list');
  if (!reasoningList) return;
  reasoningList.innerHTML = '';

  if (!reasons || !reasons.length) {
    reasoningList.innerHTML = '<li class="p-3 text-center text-[12px] text-[#64748b]">No reasoning chain generated</li>';
    return;
  }

  reasons.forEach(r => {
    let status = 'INFO';
    let text = '';

    if (typeof r === 'object' && r !== null) {
      status = (r.status || 'INFO').toUpperCase();
      text = r.text || '';
    } else {
      text = String(r);
      status = 'INFO';
    }

    let boxClass = 'p-2.5 border border-[#232f42] bg-[#0f141c]/80 flex items-start gap-2.5';
    let pillClass = 'inline-flex items-center px-1.5 py-0.5 text-[9px] font-bold font-mono bg-slate-800 text-slate-300 border border-slate-700 uppercase mt-0.5';
    let textClass = 'text-[12px] text-[#cbd5e1] leading-snug';

    if (status === 'PASSED') {
      boxClass = 'p-2.5 border border-emerald-500/30 bg-emerald-500/10 flex items-start gap-2.5';
      pillClass = 'inline-flex items-center px-1.5 py-0.5 text-[9px] font-bold font-mono bg-emerald-500/20 text-emerald-400 border border-emerald-500/40 uppercase mt-0.5';
      textClass = 'text-[12px] text-emerald-300 leading-snug';
    } else if (status === 'FLAGGED') {
      boxClass = 'p-2.5 border border-amber-500/30 bg-amber-500/10 flex items-start gap-2.5';
      pillClass = 'inline-flex items-center px-1.5 py-0.5 text-[9px] font-bold font-mono bg-amber-500/20 text-amber-400 border border-amber-500/40 uppercase mt-0.5';
      textClass = 'text-[12px] text-amber-200/90 leading-snug';
    } else if (status === 'REJECTED') {
      boxClass = 'p-2.5 border border-red-500/30 bg-red-500/10 flex items-start gap-2.5';
      pillClass = 'inline-flex items-center px-1.5 py-0.5 text-[9px] font-bold font-mono bg-red-500/20 text-red-400 border border-red-500/40 uppercase mt-0.5';
      textClass = 'text-[12px] text-red-300 leading-snug';
    }

    const li = document.createElement('li');
    li.className = boxClass;
    li.innerHTML = `
      <span class="${pillClass}">${escapeHtml(status)}</span>
      <p class="${textClass}">${escapeHtml(text)}</p>
    `;
    reasoningList.appendChild(li);
  });
}

function renderRules(checks, filter) {
  const rulesBody = $('rules-body');
  if (!rulesBody) return;
  rulesBody.innerHTML = '';

  const totalCnt = (checks || []).length;
  const excCnt = (checks || []).filter(c => c.status !== 'PASS').length;
  const passCnt = (checks || []).filter(c => c.status === 'PASS').length;

  setText('rule-cnt-all', totalCnt);
  setText('rule-cnt-exceptions', excCnt);
  setText('rule-cnt-passed', passCnt);

  const excCntSpan = $('rule-cnt-exceptions');
  if (excCntSpan) {
    if (excCnt > 0) {
      excCntSpan.className = 'text-amber-400 font-bold';
    } else {
      excCntSpan.className = '';
    }
  }

  const filtered = (checks || []).filter(chk => {
    if (filter === 'exceptions') return chk.status !== 'PASS';
    if (filter === 'passed') return chk.status === 'PASS';
    return true;
  });

  if (!filtered.length) {
    rulesBody.innerHTML = `<tr><td colspan="4" class="p-4 text-center text-[#64748b]">No rules matching filter "${escapeHtml(filter)}"</td></tr>`;
    return;
  }

  filtered.forEach(chk => {
    let statusClass = 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/35';
    const st = (chk.status || '').toUpperCase();
    if (st === 'FAIL' || st === 'BLOCK' || st === 'REJECT') {
      statusClass = 'bg-red-500/15 text-red-400 border border-red-500/35';
    } else if (st === 'WARN' || st === 'FLAG' || st === 'REVIEW') {
      statusClass = 'bg-amber-500/15 text-amber-400 border border-amber-500/35';
    } else if (st === 'SKIP') {
      statusClass = 'bg-slate-700/40 text-slate-400 border border-slate-600/50';
    } else if (st === 'INFO') {
      statusClass = 'bg-sky-500/15 text-sky-400 border border-sky-500/35';
    }

    let sevClass = 'bg-slate-800 text-slate-300 border border-slate-700';
    const sev = (chk.severity || 'info').toLowerCase();
    if (sev === 'hard' || sev === 'blocker' || sev === 'critical') {
      sevClass = 'bg-red-500/15 text-red-400 border border-red-500/35';
    } else if (sev === 'soft' || sev === 'warn' || sev === 'warning' || sev === 'medium') {
      sevClass = 'bg-amber-500/15 text-amber-400 border border-amber-500/35';
    } else if (sev === 'info' || sev === 'low') {
      sevClass = 'bg-sky-500/10 text-sky-400 border border-sky-500/30';
    }

    const tr = document.createElement('tr');
    tr.className = 'hover:bg-[#1a2434]/60 transition';
    tr.innerHTML = `
      <td class="py-2.5 px-4 font-mono font-medium text-[#dee2ee]">${escapeHtml(chk.rule)}</td>
      <td class="py-2.5 px-3 text-center">
        <span class="inline-flex px-2 py-0.5 text-[10px] font-mono font-bold ${statusClass}">
          ${escapeHtml(chk.status)}
        </span>
      </td>
      <td class="py-2.5 px-3 text-center">
        <span class="inline-flex px-2 py-0.5 text-[9px] font-mono font-bold ${sevClass}">
          ${escapeHtml(chk.severity || 'info')}
        </span>
      </td>
      <td class="py-2.5 px-4 text-[#cbd5e1]">${escapeHtml(chk.message)}</td>
    `;
    rulesBody.appendChild(tr);
  });
}

function renderTrace(traceEntries, timings) {
  const traceBody = $('trace-body');
  if (!traceBody) return;
  traceBody.innerHTML = '';

  (traceEntries || []).forEach(trEntry => {
    const tr = document.createElement('tr');
    tr.className = 'hover:bg-[#1a2434]/50 transition';
    tr.innerHTML = `
      <td class="py-2 px-4 font-mono font-medium text-[#dee2ee]">${escapeHtml(trEntry.stage)}</td>
      <td class="py-2 px-3 text-center"><span class="inline-flex px-1.5 py-0.2 text-[9px] font-mono font-bold bg-slate-800 text-slate-300 border border-slate-700">${escapeHtml(trEntry.status)}</span></td>
      <td class="py-2 px-4 font-mono text-amber-400 font-semibold">${trEntry.duration_ms} ms</td>
      <td class="py-2 px-4 text-[#cbd5e1] text-[11px]">${escapeHtml(trEntry.summary)}</td>
    `;
    traceBody.appendChild(tr);
  });

  if (timings && timings.total != null) {
    const totalEl = $('total-latency');
    if (totalEl) totalEl.textContent = `${timings.total} ms`;
  }
}

async function handleResolve(action) {
  if (!currentInvoiceId) {
    alert('Please select or persist an invoice first to apply reviewer resolution.');
    return;
  }

  const noteInput = $('review-note');
  const note = noteInput ? noteInput.value : '';
  const selectedRadio = document.querySelector('input[name="select_po_opt"]:checked');
  const poId = selectedRadio ? selectedRadio.value : activePOId;

  try {
    const res = await fetch(`/api/invoices/${currentInvoiceId}/resolve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: action === 'approve' ? 'select_po' : 'reject', po_id: poId, note: note }),
    });
    if (!res.ok) throw new Error('Failed to resolve');
    const updated = await res.json();
    DataCache.invalidate('invoices');
    DataCache.invalidate('pos');
    await renderDecisionResult(updated);
    loadCockpitQueue({ reset: true });
    if (typeof batchResults !== 'undefined' && batchResults && batchResults.length) {
      const bItem = batchResults.find(it => it.invoice_id === currentInvoiceId);
      if (bItem) {
        bItem.decision = updated.decision;
        bItem.reason_code = updated.reason_code;
        bItem.result = updated;
        renderBatchHUD();
        renderBatchTable();
      }
    }
  } catch (err) {
    alert(`Resolution error: ${err.message}`);
  }
}

// Format timestamp into exact human-readable date & time plus relative duration
function formatTimestamp(dateStr) {
  if (!dateStr) return { exact: '—', relative: '' };
  try {
    const s = dateStr.includes('T') || dateStr.endsWith('Z') ? dateStr : dateStr.replace(' ', 'T') + 'Z';
    const d = new Date(s);
    if (isNaN(d.getTime())) {
      return { exact: String(dateStr), relative: '' };
    }
    const exact = d.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      second: '2-digit',
      hour12: true,
    });
    const now = new Date();
    const diffSec = Math.floor((now.getTime() - d.getTime()) / 1000);
    let relative = '';
    if (diffSec < 45) {
      relative = 'just now';
    } else if (diffSec < 3600) {
      relative = `${Math.floor(diffSec / 60)}m ago`;
    } else if (diffSec < 86400) {
      relative = `${Math.floor(diffSec / 3600)}h ago`;
    } else {
      relative = `${Math.floor(diffSec / 86400)}d ago`;
    }
    return { exact, relative };
  } catch (e) {
    return { exact: String(dateStr), relative: '' };
  }
}

async function loadCockpitQueue({ reset = false } = {}) {
  const list = $('history-list');
  if (!list) return;

  if (reset) {
    sidebarQueueOffset = 0;
    sidebarQueueHasMore = true;
    allHistoryInvoices = [];
    list.innerHTML = `
      <div class="p-4 flex items-center justify-center gap-2 text-[12px] text-[#94a3b8]">
        <div class="spinner"></div>
        <span>Loading ledger queue...</span>
      </div>
    `;
  }

  if (sidebarQueueLoading || !sidebarQueueHasMore) return;
  sidebarQueueLoading = true;

  try {
    const queryParams = new URLSearchParams({
      paged: 'true',
      limit: String(SIDEBAR_QUEUE_LIMIT),
      offset: String(sidebarQueueOffset),
    });
    if (activeSidebarFilter && activeSidebarFilter !== 'all') {
      queryParams.set('status', activeSidebarFilter);
    }
    if (sidebarSearchQuery && sidebarSearchQuery.trim()) {
      queryParams.set('search', sidebarSearchQuery.trim());
    }

    const url = `/api/invoices?${queryParams.toString()}`;
    const data = await DataCache.fetchWithCache(url, { ttl: 45, swr: true });

    if (reset) {
      list.innerHTML = '';
    } else {
      const loadingIndicator = $('sidebar-queue-loading-more');
      if (loadingIndicator) loadingIndicator.remove();
    }

    if (data.counts) {
      setText('sidebar-ledger-count-badge', data.counts.all || 0);
      setText('chip-cnt-all', data.counts.all || 0);
      setText('chip-cnt-review', data.counts.review || 0);
      setText('chip-cnt-rejected', data.counts.rejected || 0);
      setText('chip-cnt-approved', data.counts.approved || 0);
    }

    const items = data.items || [];
    if (reset && !items.length) {
      list.innerHTML = '<div class="p-4 text-center text-[12px] text-[#64748b]">No invoices found</div>';
      sidebarQueueHasMore = false;
      return;
    }

    items.forEach(inv => {
      allHistoryInvoices.push(inv);
      appendHistoryItem(inv, list);
    });

    sidebarQueueOffset += items.length;
    sidebarQueueHasMore = Boolean(data.has_more);

    if (sidebarQueueHasMore) {
      const moreDiv = document.createElement('div');
      moreDiv.id = 'sidebar-queue-loading-more';
      moreDiv.className = 'py-2.5 text-center text-[10px] text-[#64748b] font-mono border-t border-[#1c2738]';
      moreDiv.textContent = 'Scroll for more records...';
      list.appendChild(moreDiv);
    }
  } catch (err) {
    if (reset) {
      list.innerHTML = `<div class="p-4 text-center text-[12px] text-red-400">Failed to load history (${escapeHtml(err.message)})</div>`;
    }
  } finally {
    sidebarQueueLoading = false;
  }
}

function appendHistoryItem(inv, list) {
  const isCurrent = currentInvoiceId === inv.invoice_id;
  const isRej = inv.status === 'REJECTED';
  const isApp = inv.status === 'APPROVED';

  let rowClass = 'p-2.5 hover:bg-[#1a2434]/70 transition flex items-center justify-between group cursor-pointer history-queue-item';
  if (isCurrent) {
    rowClass += isRej
      ? ' bg-red-950/30 border-l-2 border-red-500 active-queue-item'
      : ' bg-amber-500/10 border-l-2 border-amber-500 active-queue-item';
  } else if (isRej) {
    rowClass += ' hover:bg-red-950/20';
  }

  let statusBadge = 'bg-amber-500/10 text-amber-400 border border-amber-500/30';
  if (isApp) {
    statusBadge = 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30';
  } else if (isRej) {
    statusBadge = 'bg-red-500/10 text-red-400 border border-red-500/30';
  }

  const ts = formatTimestamp(inv.created_at);
  const div = document.createElement('div');
  div.className = rowClass;
  div.dataset.invoiceId = String(inv.invoice_id);
  div.innerHTML = `
    <div class="space-y-0.5 min-w-0 pr-2">
      <div class="flex items-center gap-1.5">
        <span class="font-mono text-[12px] font-bold text-[#dee2ee]">#${escapeHtml(inv.invoice_no_raw || 'N/A')}</span>
        ${isRej ? '<span class="h-1.5 w-1.5 bg-red-400"></span>' : ''}
        <span class="current-badge ${isCurrent ? '' : 'hidden'} text-[9px] font-mono text-amber-400 uppercase font-bold">[CURRENT]</span>
      </div>
      <p class="text-[11px] text-[#94a3b8] truncate font-sans">
        ${escapeHtml(inv.vendor_id || 'Unknown')} · Total: <span class="font-mono text-amber-400/90 font-semibold">${inv.currency || 'INR'} ${inv.total != null ? Number(inv.total).toLocaleString('en-IN') : '—'}</span>
      </p>
      <div class="flex items-center gap-2 text-[10px] text-[#64748b] font-mono">
        <span>${escapeHtml(ts.relative || ts.exact)}</span>
        ${inv.po_id ? `<span>·</span><span>${escapeHtml(inv.po_id)}</span>` : ''}
      </div>
    </div>
    <div class="flex flex-col items-end gap-1 flex-shrink-0">
      <span class="inline-flex items-center px-1.5 py-0.5 text-[9px] font-bold tracking-wide ${statusBadge} font-mono uppercase">
        ${escapeHtml(inv.status)}
      </span>
      <button class="h-5 px-1.5 flex items-center gap-1 bg-[#1a2434] hover:bg-[#232f42] text-[#dee2ee] text-[10px] font-medium transition border border-[#232f42] btn-view-hist-doc cursor-pointer">
        <span class="material-symbols-outlined text-[12px]">visibility</span>
        <span>View</span>
      </button>
    </div>
  `;

  const btnViewHist = div.querySelector('.btn-view-hist-doc');
  if (btnViewHist) {
    btnViewHist.addEventListener('click', (e) => {
      e.stopPropagation();
      openDocumentViewer({
        invoiceId: inv.invoice_id,
        invoiceNo: inv.invoice_no_raw,
        vendorName: inv.vendor_id,
        fileName: inv.file_name,
        filePath: inv.file_path,
      });
    });
  }

  div.addEventListener('click', () => {
    AppRouter.navigate(`/cockpit/invoices/${inv.invoice_id}`);
  });

  list.appendChild(div);
}

function updateQueueItemActiveHighlight(activeInvoiceId) {
  const items = document.querySelectorAll('.history-queue-item');
  items.forEach(item => {
    const isAct = Number(item.dataset.invoiceId) === Number(activeInvoiceId);
    const badge = item.querySelector('.current-badge');
    if (isAct) {
      item.classList.add('bg-amber-500/10', 'border-l-2', 'border-amber-500');
      if (badge) badge.classList.remove('hidden');
    } else {
      item.classList.remove('bg-amber-500/10', 'border-l-2', 'border-amber-500', 'bg-red-950/30', 'border-red-500');
      if (badge) badge.classList.add('hidden');
    }
  });
}

async function loadCockpitInvoice(invoiceId, openDoc = false) {
  if (!invoiceId) return;
  currentInvoiceId = Number(invoiceId);
  updateQueueItemActiveHighlight(currentInvoiceId);

  try {
    const fullData = await DataCache.fetchWithCache(`/api/invoices/${encodeURIComponent(invoiceId)}`, { ttl: 300, swr: true });
    await renderDecisionResult(fullData);

    if (openDoc) {
      openDocumentViewer({
        invoiceId: fullData.invoice_id || invoiceId,
        invoiceNo: (fullData.extracted && fullData.extracted.invoice_number && fullData.extracted.invoice_number.value) || fullData.invoice_no_raw,
        vendorName: (fullData.extracted && fullData.extracted.vendor && fullData.extracted.vendor.name) || fullData.vendor_name || fullData.vendor_id,
        fileName: fullData.file_name,
        filePath: fullData.file_path,
      });
    }
  } catch (err) {
    console.error('Failed to load invoice details:', err);
  }
}

// Global aliases for backward compatibility
const loadHistory = () => loadCockpitQueue({ reset: true });
const renderFilteredHistory = () => loadCockpitQueue({ reset: true });
const loadPOs = () => {};

function initAppRoutes() {
  AppRouter
    .add('/cockpit', ({ query }) => {
      switchWorkspace('ws-single');
      if (query.tab) {
        window.switchSidebarTab(query.tab);
      }
      if (query.filter && query.filter !== activeSidebarFilter) {
        activeSidebarFilter = query.filter;
        syncSidebarChipUI();
      }
      loadCockpitQueue({ reset: true });
    })
    .add('/cockpit/invoices/:id', ({ params, query }) => {
      switchWorkspace('ws-single');
      if (query.tab) {
        window.switchSidebarTab(query.tab);
      }
      loadCockpitInvoice(params.id, query.doc === '1');
      if (!allHistoryInvoices.length) {
        loadCockpitQueue({ reset: false });
      }
    })
    .add('/pos', ({ query }) => {
      switchWorkspace('ws-pos');
      loadPOHubController({ search: query.search || '' });
    })
    .add('/pos/:po_id', ({ params }) => {
      switchWorkspace('ws-pos');
      loadPOHubController({ poId: params.po_id });
    })
    .add('/batch', () => {
      switchWorkspace('ws-batch');
    });
}

function syncSidebarChipUI() {
  const chips = document.querySelectorAll('.sidebar-chip');
  chips.forEach(c => {
    if ((c.dataset.filter || 'all') === activeSidebarFilter) {
      c.className = 'sidebar-chip px-2 py-0.5 bg-amber-500 text-slate-950 font-bold whitespace-nowrap active cursor-pointer';
    } else {
      c.className = 'sidebar-chip px-2 py-0.5 bg-[#161f2c] border border-[#232f42] text-[#94a3b8] hover:text-[#dee2ee] transition whitespace-nowrap cursor-pointer';
    }
  });
}

async function handleSeedDemo() {
  try {
    const res = await fetch('/api/health');
    alert('Demo database is ready and loaded from samples/seed.json.');
    DataCache.invalidate();
    loadCockpitQueue({ reset: true });
    loadPOHubController();
  } catch (err) {
    alert('Error connecting to API');
  }
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/* ==========================================================================
   WORKSPACE 1 & 2 & 3: NAVIGATION CONTROLS
   ========================================================================== */
let currentOriginWorkspace = 'ws-single';

function initWorkspaceNav() {
  const tabs = document.querySelectorAll('.workspace-tab');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      const wsId = tab.dataset.workspace;
      if (wsId === 'ws-single') {
        if (currentInvoiceId) AppRouter.navigate(`/cockpit/invoices/${currentInvoiceId}`);
        else AppRouter.navigate('/cockpit');
      } else if (wsId === 'ws-batch') {
        AppRouter.navigate('/batch');
      } else if (wsId === 'ws-pos') {
        if (selectedPOId) AppRouter.navigate(`/pos/${encodeURIComponent(selectedPOId)}`);
        else AppRouter.navigate('/pos');
      }
    });
  });

  const btnBack = $('btn-back-to-origin');
  if (btnBack) {
    btnBack.addEventListener('click', () => {
      if (currentOriginWorkspace === 'ws-batch') AppRouter.navigate('/batch');
      else if (currentOriginWorkspace === 'ws-pos') AppRouter.navigate('/pos');
      else AppRouter.navigate('/cockpit');
      hideBreadcrumb();
    });
  }
}

function switchWorkspace(targetId) {
  document.querySelectorAll('.workspace-tab').forEach(t => {
    if (t.dataset.workspace === targetId) {
      t.classList.add('active', 'border-b-2', 'border-amber-500', 'text-amber-400');
      t.classList.remove('text-[#94a3b8]');
    } else {
      t.classList.remove('active', 'border-b-2', 'border-amber-500', 'text-amber-400');
      t.classList.add('text-[#94a3b8]');
    }
  });

  document.querySelectorAll('.workspace-view').forEach(v => {
    if (v.id === targetId) v.classList.remove('hidden');
    else v.classList.add('hidden');
  });
}

function showBreadcrumb(originWs, invoiceNo) {
  currentOriginWorkspace = originWs;
  const bc = $('inspector-breadcrumb');
  const label = $('breadcrumb-origin-label');
  const invNo = $('breadcrumb-inv-no');
  if (label) label.textContent = originWs === 'ws-batch' ? 'Batch Processing' : 'Purchase Orders Hub';
  if (invNo) invNo.textContent = invoiceNo || 'Selected';
  if (bc) bc.classList.remove('hidden');
}

function hideBreadcrumb() {
  const bc = $('inspector-breadcrumb');
  if (bc) bc.classList.add('hidden');
}

/* ==========================================================================
   WORKSPACE 2: BATCH PROCESSING CLIENT
   ========================================================================== */
let stagedBatchFiles = [];
let batchResults = [];
let currentBatchFilter = 'all';
let currentBatchSort = 'priority';

function initBatchWorkspace() {
  const dropZone = $('batch-drop-zone');
  const fileInput = $('batch-file-input');
  const btnProcess = $('btn-batch-process');
  const btnClear = $('btn-batch-clear');
  const sortSelect = $('batch-sort-select');

  if (dropZone && fileInput) {
    fileInput.addEventListener('change', () => {
      if (fileInput.files.length) {
        handleBatchFilesSelect(Array.from(fileInput.files));
      }
    });

    dropZone.addEventListener('dragover', (e) => {
      e.preventDefault();
      dropZone.classList.add('drag-over');
    });

    dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));

    dropZone.addEventListener('drop', (e) => {
      e.preventDefault();
      dropZone.classList.remove('drag-over');
      if (e.dataTransfer.files.length) {
        handleBatchFilesSelect(Array.from(e.dataTransfer.files));
      }
    });
  }

  if (btnClear) {
    btnClear.addEventListener('click', () => {
      stagedBatchFiles = [];
      if (fileInput) fileInput.value = '';
      renderBatchStaging();
    });
  }

  if (btnProcess) {
    btnProcess.addEventListener('click', handleBatchProcess);
  }

  // Filter pills
  const filterBtns = document.querySelectorAll('.batch-filter-btn');
  filterBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      filterBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentBatchFilter = btn.dataset.bfilter;
      renderBatchTable();
    });
  });

  // Sort dropdown
  if (sortSelect) {
    sortSelect.addEventListener('change', () => {
      currentBatchSort = sortSelect.value;
      renderBatchTable();
    });
  }
}

function handleBatchFilesSelect(files) {
  // Append new files without duplicating names
  files.forEach(f => {
    if (!stagedBatchFiles.some(existing => existing.name === f.name && existing.size === f.size)) {
      stagedBatchFiles.push(f);
    }
  });
  renderBatchStaging();
}

function renderBatchStaging() {
  const countSpan = $('batch-staged-count');
  const list = $('batch-staged-list');
  const btnProcess = $('btn-batch-process');
  const btnClear = $('btn-batch-clear');

  if (countSpan) countSpan.textContent = stagedBatchFiles.length;

  if (btnClear) {
    btnClear.style.display = stagedBatchFiles.length ? 'inline-block' : 'none';
  }

  if (btnProcess) {
    btnProcess.disabled = stagedBatchFiles.length === 0;
    btnProcess.textContent = `Process Batch (${stagedBatchFiles.length} file${stagedBatchFiles.length === 1 ? '' : 's'})`;
  }

  if (!list) return;
  if (!stagedBatchFiles.length) {
    list.innerHTML = '<div class="empty-state">No files selected yet. Drag files or browse above.</div>';
    return;
  }

  list.innerHTML = '';
  stagedBatchFiles.forEach((f, idx) => {
    const chip = document.createElement('div');
    chip.className = 'batch-file-chip';
    const sizeKb = Math.round(f.size / 1024);
    chip.innerHTML = `
      <span>📄 <strong>${escapeHtml(f.name)}</strong> <span class="hint">(${sizeKb} KB)</span></span>
      <button class="remove-chip" title="Remove file" data-idx="${idx}">✕</button>
    `;
    chip.querySelector('.remove-chip').addEventListener('click', (e) => {
      e.stopPropagation();
      stagedBatchFiles.splice(idx, 1);
      renderBatchStaging();
    });
    list.appendChild(chip);
  });
}

async function handleBatchProcess() {
  if (!stagedBatchFiles.length) return;

  const btnProcess = $('btn-batch-process');
  const progressContainer = $('batch-progress-container');
  const progressStatus = $('batch-progress-status');
  const progressPct = $('batch-progress-pct');
  const progressBarFill = $('batch-progress-bar-fill');
  const substatusText = $('batch-substatus-text');
  const timerLabel = $('batch-progress-timer');
  const ocrEngine = $('batch-ocr-select') ? $('batch-ocr-select').value : '';
  const isDryRun = $('batch-dryrun-toggle') ? $('batch-dryrun-toggle').checked : false;

  if (btnProcess) btnProcess.disabled = true;
  if (progressContainer) progressContainer.classList.remove('hidden');

  // Reset results and render empty/current table
  batchResults = [];
  renderBatchTable();

  const totalFiles = stagedBatchFiles.length;
  if (progressStatus) progressStatus.textContent = `Processing file 1 of ${totalFiles}...`;
  if (progressPct) progressPct.textContent = '0%';
  if (progressBarFill) {
    progressBarFill.style.width = '0%';
    progressBarFill.style.backgroundColor = '#f59e0b';
  }
  if (substatusText) substatusText.textContent = 'Uploading files & preparing batch pipeline...';

  const startTime = Date.now();
  const timerInterval = setInterval(() => {
    if (timerLabel) {
      const elapsedSec = Math.round((Date.now() - startTime) / 1000);
      const completed = batchResults.length;
      if (completed > 0 && completed < totalFiles) {
        const avgPerFile = (Date.now() - startTime) / completed;
        const estRemSec = Math.max(1, Math.round(((totalFiles - completed) * avgPerFile) / 1000));
        timerLabel.textContent = `Elapsed: ${elapsedSec}s • Est. rem: ~${estRemSec}s`;
      } else {
        timerLabel.textContent = `Elapsed: ${elapsedSec}s`;
      }
    }
  }, 400);

  const formData = new FormData();
  stagedBatchFiles.forEach(file => {
    formData.append('files', file);
  });

  let url = `/api/invoices/batch/stream?dry_run=${isDryRun}`;
  if (ocrEngine) url += `&ocr_engine=${ocrEngine}`;

  try {
    const res = await fetch(url, { method: 'POST', body: formData });
    if (!res.ok) throw new Error(`Batch processing returned status ${res.status}`);

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let batchCompleteData = null;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const blocks = buffer.split('\n\n');
      buffer = blocks.pop() || '';

      for (const block of blocks) {
        if (!block.trim()) continue;
        const line = block.split('\n').find(l => l.startsWith('data: '));
        if (!line) continue;

        try {
          const payload = JSON.parse(line.replace(/^data:\s*/, ''));

          if (payload.type === 'file_start') {
            const currentFileNum = payload.file_index + 1;
            if (progressStatus) {
              progressStatus.textContent = `Processing file ${currentFileNum} of ${payload.total_files}: ${payload.file_name}`;
            }
            if (substatusText) {
              substatusText.textContent = `[${payload.file_name}] Extracting text...`;
            }
          } else if (payload.type === 'file_progress') {
            if (substatusText) {
              substatusText.textContent = `[${payload.file_name}] ${payload.message}`;
            }
            if (payload.overall_pct != null) {
              const opct = Math.min(99, Math.round(payload.overall_pct));
              if (progressPct) progressPct.textContent = `${opct}%`;
              if (progressBarFill) progressBarFill.style.width = `${opct}%`;
            }
          } else if (payload.type === 'file_done') {
            if (payload.item) {
              batchResults.unshift(payload.item);
              renderBatchHUD(payload.stats);
              renderBatchTable();
            }

            const badge = $('batch-nav-count');
            if (badge) {
              badge.textContent = batchResults.length;
              badge.classList.remove('hidden');
            }

            const currentFileNum = payload.file_index + 1;
            const pct = Math.round((currentFileNum / payload.total_files) * 100);
            if (progressBarFill) progressBarFill.style.width = `${pct}%`;
            if (progressPct) progressPct.textContent = `${pct}%`;
            if (progressStatus) {
              progressStatus.textContent = `Completed ${currentFileNum} of ${payload.total_files} files...`;
            }
          } else if (payload.type === 'batch_done') {
            batchCompleteData = payload.batch;
          } else if (payload.type === 'error') {
            throw new Error(payload.error || 'Batch processing failure');
          }
        } catch (e) {
          console.warn('Batch SSE parse warning:', e);
        }
      }
    }

    if (progressBarFill) {
      progressBarFill.style.width = '100%';
      progressBarFill.style.backgroundColor = '#16a34a';
    }
    if (progressPct) progressPct.textContent = '100%';
    const duration = Math.round((Date.now() - startTime) / 1000);
    if (progressStatus) {
      progressStatus.textContent = `Completed batch of ${batchResults.length} files in ${duration}s.`;
    }
    if (substatusText) {
      substatusText.textContent = `All files processed successfully.`;
    }

    if (batchCompleteData) {
      renderBatchHUD(batchCompleteData);
    }
    renderBatchTable();
    loadHistory();
    loadPOs();
  } catch (err) {
    alert(`Batch error: ${err.message}`);
    if (progressStatus) progressStatus.textContent = `Failed: ${err.message}`;
    if (substatusText) substatusText.textContent = err.message;
  } finally {
    clearInterval(timerInterval);
    if (btnProcess) btnProcess.disabled = false;
  }
}

function renderBatchHUD(batchData) {
  const hudSection = $('batch-hud-section');
  if (hudSection) hudSection.classList.remove('hidden');

  const total = batchResults.length;
  const reviewCount = batchResults.filter(it => it.decision === 'NEEDS_REVIEW').length;
  const approvedCount = batchResults.filter(it => it.decision === 'APPROVED').length;
  const rejectedCount = batchResults.filter(it => it.decision === 'REJECTED' || it.status === 'FAILED').length;

  const reviewPct = total > 0 ? Math.round((reviewCount / total) * 100) : 0;
  const approvedPct = total > 0 ? Math.round((approvedCount / total) * 100) : 0;
  const rejectedPct = total > 0 ? Math.round((rejectedCount / total) * 100) : 0;

  setText('hud-total-val', total);
  if (batchData && batchData.total_duration_ms != null) {
    setText('hud-duration-val', `${batchData.total_duration_ms} ms total`);
  }

  setText('hud-review-val', reviewCount);
  setText('hud-review-pct', `${reviewPct}%`);

  setText('hud-approved-val', approvedCount);
  setText('hud-approved-pct', `${approvedPct}%`);

  setText('hud-rejected-val', rejectedCount);
  setText('hud-rejected-pct', `${rejectedPct}%`);

  // Average confidence
  const confScores = batchResults.map(it => Number(it.confidence) || 0).filter(c => c > 0);
  const avgConf = confScores.length ? (confScores.reduce((a, b) => a + b, 0) / confScores.length) : 0;
  setText('hud-avg-conf-val', avgConf > 0 ? avgConf.toFixed(2) : '—');

  const confTier = getConfidenceTier(avgConf);
  const tierPill = $('hud-conf-tier-pill');
  if (tierPill) {
    tierPill.className = `confidence-tier-pill ${confTier.tier === 'green' ? 'tier-green' : (confTier.tier === 'amber' ? 'tier-amber' : 'tier-red')}`;
    tierPill.textContent = confTier.label;
  }

  const confBarFill = $('hud-conf-bar-fill');
  if (confBarFill) {
    confBarFill.style.width = `${Math.round(avgConf * 100)}%`;
    confBarFill.style.backgroundColor = confTier.barColor;
  }

  // Update filter pill counts
  setText('bfilter-cnt-all', total);
  setText('bfilter-cnt-review', reviewCount);
  setText('bfilter-cnt-approved', approvedCount);
  setText('bfilter-cnt-rejected', rejectedCount);
}

function getBatchSortedItems() {
  let items = [...batchResults];
  if (currentBatchFilter !== 'all') {
    if (currentBatchFilter === 'REJECTED') {
      items = items.filter(it => it.decision === 'REJECTED' || it.status === 'FAILED');
    } else {
      items = items.filter(it => it.decision === currentBatchFilter);
    }
  }

  items.sort((a, b) => {
    if (currentBatchSort === 'priority') {
      // Priority sorting:
      // 1. NEEDS_REVIEW first, ranked by LOWEST confidence first!
      // 2. FAILED/REJECTED second
      // 3. APPROVED last (highest confidence at bottom)
      const rankOrder = { 'NEEDS_REVIEW': 1, 'FAILED': 2, 'REJECTED': 3, 'APPROVED': 4 };
      const rankA = a.status === 'FAILED' ? 2 : (rankOrder[a.decision] || 5);
      const rankB = b.status === 'FAILED' ? 2 : (rankOrder[b.decision] || 5);
      if (rankA !== rankB) return rankA - rankB;
      return (Number(a.confidence) || 0) - (Number(b.confidence) || 0);
    } else if (currentBatchSort === 'conf_asc') {
      return (Number(a.confidence) || 0) - (Number(b.confidence) || 0);
    } else if (currentBatchSort === 'conf_desc') {
      return (Number(b.confidence) || 0) - (Number(a.confidence) || 0);
    } else if (currentBatchSort === 'time_desc') {
      return (b.processed_at || '').localeCompare(a.processed_at || '');
    } else if (currentBatchSort === 'total_desc') {
      return (Number(b.total) || 0) - (Number(a.total) || 0);
    } else if (currentBatchSort === 'name_asc') {
      return (a.file_name || '').localeCompare(b.file_name || '');
    }
    return 0;
  });

  return items;
}

function renderBatchTable() {
  const tbody = $('batch-table-body');
  if (!tbody) return;

  const items = getBatchSortedItems();
  if (!items.length) {
    tbody.innerHTML = `<tr><td colspan="9" class="empty-state">No invoices match the selected filter.</td></tr>`;
    return;
  }

  tbody.innerHTML = '';
  items.forEach((item, index) => {
    const tr = document.createElement('tr');
    tr.className = 'batch-item-row';

    // Priority Rank Badge
    let rankBadge = '';
    if (item.decision === 'NEEDS_REVIEW') {
      rankBadge = `<span class="priority-rank-badge priority-rank-1">⚠️ Action #${index + 1}</span>`;
    } else if (item.decision === 'REJECTED' || item.status === 'FAILED') {
      rankBadge = `<span class="priority-rank-badge priority-rank-2">⛔ Flagged</span>`;
    } else {
      rankBadge = `<span class="priority-rank-badge priority-rank-ok">✓ Auto-Passed</span>`;
    }

    // Status Pill
    let statusPill = '';
    if (item.status === 'FAILED') {
      statusPill = `<span class="badge badge-red">FAILED</span>`;
    } else if (item.decision === 'APPROVED') {
      statusPill = `<span class="badge badge-green">APPROVED</span>`;
    } else if (item.decision === 'REJECTED') {
      statusPill = `<span class="badge badge-red">REJECTED</span>`;
    } else {
      statusPill = `<span class="badge badge-amber">NEEDS_REVIEW</span>`;
    }

    // Confidence Score & Bar
    const confVal = Number(item.confidence) || 0;
    const tier = getConfidenceTier(confVal);
    const confHtml = `
      <div class="mini-conf-bar">
        <div class="mini-bar-track">
          <div class="mini-bar-fill" style="width: ${Math.round(confVal * 100)}%; background-color: ${tier.barColor};"></div>
        </div>
        <span style="font-weight:700; color: ${tier.barColor}; font-size: 0.78rem;">${(confVal * 100).toFixed(0)}%</span>
      </div>
    `;

    // Timestamp
    const ts = formatTimestamp(item.processed_at);
    const timeHtml = `
      <div class="timestamp-cell">
        <span class="timestamp-exact">${escapeHtml(ts.exact)}</span>
        <span class="timestamp-relative">${escapeHtml(ts.relative)}</span>
      </div>
    `;

    const invoiceNoDisplay = item.invoice_no ? `#${escapeHtml(item.invoice_no)}` : '—';
    const amountDisplay = item.total != null ? `${item.currency || '₹'} ${Number(item.total).toLocaleString('en-IN')}` : '—';
    const reasonDisplay = item.reason_code ? `<span class="reason-code-badge" style="font-size:0.7rem; padding:2px 6px;">${escapeHtml(item.reason_code)}</span>` : (item.error_message ? `<span class="hint text-red">${escapeHtml(item.error_message)}</span>` : '—');

    tr.innerHTML = `
      <td>${rankBadge}</td>
      <td>
        <strong>${invoiceNoDisplay}</strong>
        <div class="hint" title="${escapeHtml(item.file_name)}">${escapeHtml(item.file_name)}</div>
      </td>
      <td>
        <div><strong>${escapeHtml(item.vendor_name || item.vendor_id || 'Unknown')}</strong></div>
      </td>
      <td><strong>${amountDisplay}</strong></td>
      <td>${statusPill}</td>
      <td>${reasonDisplay}</td>
      <td>${confHtml}</td>
      <td>${timeHtml}</td>
      <td>
        <div class="action-btn-group">
          <button class="btn btn-sm btn-outline btn-view-batch-doc" title="Preview Original Document">📄 View</button>
          <button class="btn btn-sm btn-outline btn-inspect-item">Inspect</button>
        </div>
      </td>
    `;

    const btnViewDoc = tr.querySelector('.btn-view-batch-doc');
    if (btnViewDoc) {
      btnViewDoc.addEventListener('click', (e) => {
        e.stopPropagation();
        openDocumentViewer({
          invoiceId: item.invoice_id,
          invoiceNo: item.invoice_no,
          vendorName: item.vendor_name || item.vendor_id,
          fileName: item.file_name,
          filePath: item.file_path,
        });
      });
    }

    const btnInspect = tr.querySelector('.btn-inspect-item');
    if (btnInspect) {
      btnInspect.addEventListener('click', async (e) => {
        e.stopPropagation();
        await inspectBatchItem(item);
      });
    }

    tr.addEventListener('click', async () => {
      await inspectBatchItem(item);
    });

    tbody.appendChild(tr);
  });
}

async function inspectBatchItem(item) {
  if (item.invoice_id) {
    currentInvoiceId = item.invoice_id;
  }
  showBreadcrumb('ws-batch', item.invoice_no || item.file_name);
  switchWorkspace('ws-single');

  if (item.result) {
    await renderDecisionResult(item.result);
  } else if (item.invoice_id) {
    const res = await fetch(`/api/invoices/${item.invoice_id}`);
    const data = await res.json();
    await renderDecisionResult(data);
  } else {
    alert(`File "${item.file_name}" failed before generating a ledger record: ${item.error_message || 'Unknown failure'}`);
  }
}

/* ==========================================================================
   WORKSPACE 3: PURCHASE ORDERS HUB CLIENT
   ========================================================================== */
let poListData = [];
let selectedPOId = null;
let currentPOFilter = 'ALL';
let currentPOSearch = '';

function initPOHub() {
  const searchInput = $('po-search-input');
  if (searchInput) {
    const debouncedPOSearch = debounce((val) => {
      currentPOSearch = val;
      loadPOHubController({ search: val });
    }, 250);

    searchInput.addEventListener('input', (e) => {
      debouncedPOSearch(e.target.value.toLowerCase().trim());
    });
  }

  const filterSelect = $('po-filter-status');
  if (filterSelect) {
    filterSelect.addEventListener('change', (e) => {
      currentPOFilter = e.target.value.toUpperCase();
      renderPOMasterTable();
    });
  }

  const closeBtn = $('pod-close-btn');
  if (closeBtn) {
    closeBtn.addEventListener('click', () => {
      const detailCard = $('po-detail-card');
      if (detailCard) detailCard.classList.add('hidden');
      const emptyCard = $('po-detail-empty');
      if (emptyCard) emptyCard.classList.remove('hidden');
      selectedPOId = null;
      document.querySelectorAll('#pos-master-tbody tr').forEach(r => {
        r.classList.remove('bg-amber-500/10', 'border-l-2', 'border-amber-500');
      });
      AppRouter.navigate('/pos');
    });
  }
}

async function loadPOHubController({ search = '', poId = null } = {}) {
  try {
    const queryParams = new URLSearchParams({ paged: 'true', limit: '50', offset: '0' });
    if (search && search.trim()) queryParams.set('search', search.trim());

    const url = `/api/pos?${queryParams.toString()}`;
    const data = await DataCache.fetchWithCache(url, { ttl: 60, swr: true });

    poListData = data.items || [];

    const navBadge = $('po-nav-count');
    if (navBadge) navBadge.textContent = data.total || poListData.length;

    renderPOSummaryKPIs(data.total || poListData.length);
    renderPOMasterTable();

    if (poId) {
      selectPODetail(poId);
    } else if (!selectedPOId && poListData.length) {
      selectPODetail(poListData[0].po_id);
    } else if (!poListData.length) {
      const detailCard = $('po-detail-card');
      if (detailCard) detailCard.classList.add('hidden');
      const emptyCard = $('po-detail-empty');
      if (emptyCard) emptyCard.classList.remove('hidden');
    }
  } catch (err) {
    console.error('Failed to load PO Hub:', err);
  }
}

const loadPOHub = () => loadPOHubController();

function renderPOSummaryKPIs(totalCountOverride) {
  const totalCount = totalCountOverride != null ? totalCountOverride : poListData.length;
  const totalBudget = poListData.reduce((sum, p) => sum + (Number(p.total_budget || p.total) || 0), 0);
  const totalBilled = poListData.reduce((sum, p) => sum + (Number(p.billed_total) || 0), 0);
  const remainingHeadroom = Math.max(0, totalBudget - totalBilled);

  setText('pos-stat-total-count', totalCount);
  setText('pos-stat-total-budget', `₹ ${totalBudget.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`);
  setText('pos-stat-total-billed', `₹ ${totalBilled.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`);
  setText('pos-stat-total-rem', `₹ ${remainingHeadroom.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`);
}

function getFilteredPOs() {
  return poListData.filter(po => {
    if (currentPOFilter && currentPOFilter !== 'ALL') {
      if ((po.status || '').toUpperCase() !== currentPOFilter) {
        return false;
      }
    }
    if (currentPOSearch) {
      const idMatch = (po.po_id || '').toLowerCase().includes(currentPOSearch);
      const vendorMatch = (po.vendor_name || po.vendor_id || '').toLowerCase().includes(currentPOSearch);
      if (!idMatch && !vendorMatch) return false;
    }
    return true;
  });
}

function renderPOMasterTable() {
  const tbody = $('pos-master-tbody');
  if (!tbody) return;

  const list = getFilteredPOs();
  if (!list.length) {
    tbody.innerHTML = `<tr><td colspan="5" class="p-6 text-center text-[#64748b]">No purchase orders found matching current criteria.</td></tr>`;
    return;
  }

  tbody.innerHTML = '';
  list.forEach(po => {
    const tr = document.createElement('tr');
    const isSelected = selectedPOId === po.po_id;
    tr.className = `hover:bg-[#1a2434]/60 transition cursor-pointer ${isSelected ? 'bg-amber-500/10 border-l-2 border-amber-500' : ''}`;

    const budget = Number(po.total_budget || po.total) || 0;
    const billed = Number(po.billed_total) || 0;
    const remaining = Number(po.remaining_balance) || Math.max(0, budget - billed);
    const utilPct = budget > 0 ? Math.min(100, Math.round((billed / budget) * 100)) : 0;

    let statusPill = 'bg-amber-500/10 text-amber-400 border border-amber-500/30';
    if (po.status === 'OPEN') statusPill = 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30';
    else if (po.status === 'CLOSED') statusPill = 'bg-slate-800 text-slate-300 border border-slate-700';

    tr.innerHTML = `
      <td class="py-2.5 px-3">
        <strong class="font-mono text-[13px] text-amber-400">${escapeHtml(po.po_id)}</strong>
        <div class="text-[10px] text-[#64748b] font-mono">${escapeHtml(po.po_date || '—')}</div>
      </td>
      <td class="py-2.5 px-3">
        <div class="font-medium text-[#dee2ee] text-[12px] truncate max-w-[150px]">${escapeHtml(po.vendor_name || po.vendor_id)}</div>
        <div class="text-[10px] text-[#64748b] font-mono">${escapeHtml(po.vendor_id)}</div>
      </td>
      <td class="py-2.5 px-3 font-mono font-bold text-[#dee2ee]">
        ₹ ${budget.toLocaleString('en-IN')}
      </td>
      <td class="py-2.5 px-3">
        <div class="flex items-center gap-1.5">
          <div class="w-16 bg-[#1a2434] h-1.5 overflow-hidden border border-[#232f42]">
            <div class="${utilPct > 90 ? 'bg-red-500' : 'bg-emerald-400'} h-full" style="width: ${utilPct}%;"></div>
          </div>
          <span class="font-mono text-[11px] text-[#94a3b8]">${utilPct}%</span>
        </div>
        <div class="text-[10px] text-[#64748b] font-mono">Rem: ₹ ${remaining.toLocaleString('en-IN')}</div>
      </td>
      <td class="py-2.5 px-2 text-center">
        <span class="inline-flex px-1.5 py-0.5 text-[10px] font-mono font-bold ${statusPill}">
          ${escapeHtml(po.status)}
        </span>
      </td>
    `;

    tr.addEventListener('click', () => {
      document.querySelectorAll('#pos-master-tbody tr').forEach(r => {
        r.classList.remove('bg-amber-500/10', 'border-l-2', 'border-amber-500');
      });
      tr.classList.add('bg-amber-500/10', 'border-l-2', 'border-amber-500');
      AppRouter.navigate('/pos/' + encodeURIComponent(po.po_id));
    });

    tbody.appendChild(tr);
  });
}

async function selectPODetail(poId) {
  selectedPOId = poId;
  const detailCard = $('po-detail-card');
  const emptyCard = $('po-detail-empty');
  if (emptyCard) emptyCard.classList.add('hidden');
  if (detailCard) detailCard.classList.remove('hidden');

  try {
    const data = await DataCache.fetchWithCache(`/api/pos/${encodeURIComponent(poId)}`, { ttl: 120, swr: true });
    if (data.error) {
      console.error('PO error:', data.error);
      return;
    }
    renderPODetail(data);
  } catch (err) {
    console.error('Failed to load PO details for:', poId, err);
  }
}

function renderPODetail(data) {
  const po = data.po || {};
  const vendor = data.vendor || {};
  const balance = data.balance || {};
  const items = data.items || [];
  const invoices = data.invoices || [];

  setText('pod-title-id', po.po_id || 'PO Master');
  const statusBadge = $('pod-status-badge');
  if (statusBadge) {
    statusBadge.textContent = po.status || 'OPEN';
    statusBadge.className = `px-2 py-0.5 text-[10px] font-mono font-bold ${po.status === 'OPEN' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30' : (po.status === 'CLOSED' ? 'bg-slate-800 text-slate-300 border border-slate-700' : 'bg-amber-500/10 text-amber-400 border border-amber-500/30')}`;
  }

  setText('pod-vendor-name', vendor.name || po.vendor_name || po.vendor_id || 'Unknown Vendor');
  setText('pod-created-date', po.po_date || '—');

  // Balances
  const budget = Number(balance.total_budget || po.total) || 0;
  const approved = Number(balance.billed_approved) || 0;
  const pending = Number(balance.billed_pending) || 0;
  const remaining = Number(balance.remaining_balance) || Math.max(0, budget - (approved + pending));
  const utilPct = Number(balance.utilization_pct) || (budget > 0 ? Math.round(((approved + pending) / budget) * 100) : 0);

  setText('pod-total-budget', `₹ ${budget.toLocaleString('en-IN')}`);
  setText('pod-approved-billed', `₹ ${approved.toLocaleString('en-IN')}`);
  setText('pod-pending-billed', `₹ ${pending.toLocaleString('en-IN')}`);
  setText('pod-remaining-headroom', `₹ ${remaining.toLocaleString('en-IN')}`);
  setText('pod-util-pct', `${utilPct}%`);

  const overageWarning = $('pod-overage-warning');
  if (overageWarning) {
    if (balance.is_overbilled || (approved + pending) > budget) {
      overageWarning.classList.remove('hidden');
    } else {
      overageWarning.classList.add('hidden');
    }
  }

  // Multi-segment balance bar
  const appPct = budget > 0 ? Math.min(100, Math.round((approved / budget) * 100)) : 0;
  const pendPct = budget > 0 ? Math.min(100 - appPct, Math.round((pending / budget) * 100)) : 0;
  const remPct = Math.max(0, 100 - (appPct + pendPct));

  const barApp = $('pod-bar-approved');
  const barPend = $('pod-bar-pending');
  const barRem = $('pod-bar-remaining');
  if (barApp) barApp.style.width = `${appPct}%`;
  if (barPend) barPend.style.width = `${pendPct}%`;
  if (barRem) barRem.style.width = `${remPct}%`;

  // Line items
  const itemsTbody = $('pod-items-tbody');
  if (itemsTbody) {
    if (!items.length) {
      itemsTbody.innerHTML = `<tr><td colspan="4" class="p-4 text-center text-[#64748b]">No line items specified</td></tr>`;
    } else {
      itemsTbody.innerHTML = '';
      items.forEach(it => {
        const tr = document.createElement('tr');
        const qtyOrd = Number(it.qty_ordered) || 0;
        const qtyRem = Number(it.qty_remaining) || 0;
        const unitP = Number(it.unit_price) || 0;
        tr.innerHTML = `
          <td class="py-1.5 px-2">
            <strong class="text-[#dee2ee]">${escapeHtml(it.item_name)}</strong>
            <div class="text-[10px] text-[#64748b]">${escapeHtml(it.description || '')}</div>
          </td>
          <td class="py-1.5 px-2 font-mono text-[#cbd5e1]">${qtyOrd} ${escapeHtml(it.uom || 'units')}</td>
          <td class="py-1.5 px-2 font-mono"><strong class="${qtyRem > 0 ? 'text-emerald-400' : 'text-[#64748b]'}">${qtyRem}</strong></td>
          <td class="py-1.5 px-2 font-mono text-amber-400">₹ ${unitP.toLocaleString('en-IN')}</td>
        `;
        itemsTbody.appendChild(tr);
      });
    }
  }

  // Linked Invoices Ledger
  setText('pod-linked-count', invoices.length);
  const invsTbody = $('pod-invoices-tbody');
  if (invsTbody) {
    if (!invoices.length) {
      invsTbody.innerHTML = `<tr><td colspan="5" class="p-4 text-center text-[#64748b]">No invoices linked to this PO yet. Process invoices matching this PO to see them here.</td></tr>`;
    } else {
      invsTbody.innerHTML = '';
      invoices.forEach(inv => {
        const tr = document.createElement('tr');
        const ts = formatTimestamp(inv.created_at);
        const amt = Number(inv.total) || 0;
        let statusBadge = 'bg-amber-500/10 text-amber-400 border border-amber-500/30';
        if (inv.status === 'APPROVED') statusBadge = 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30';
        else if (inv.status === 'REJECTED') statusBadge = 'bg-red-500/10 text-red-400 border border-red-500/30';

        tr.innerHTML = `
          <td class="py-1.5 px-2 font-mono font-medium text-amber-400">#${escapeHtml(inv.invoice_no_raw || inv.invoice_id)}</td>
          <td class="py-1.5 px-2 font-mono text-[#cbd5e1]">${escapeHtml(inv.invoice_date || '—')}</td>
          <td class="py-1.5 px-2 font-mono font-bold text-[#dee2ee]">${inv.currency || '₹'} ${amt.toLocaleString('en-IN')}</td>
          <td class="py-1.5 px-2"><span class="inline-flex px-1.5 py-0.2 text-[9px] font-mono font-bold ${statusBadge}">${escapeHtml(inv.status)}</span></td>
          <td class="py-1.5 px-2 text-right">
            <div class="flex items-center justify-end gap-1">
              <button class="h-6 px-2 flex items-center gap-1 bg-[#1a2434] hover:bg-[#232f42] text-[#dee2ee] text-[10px] font-medium border border-[#232f42] transition btn-view-po-doc cursor-pointer">
                <span class="material-symbols-outlined text-[12px]">visibility</span> View
              </button>
              <button class="h-6 px-2 flex items-center gap-1 bg-[#1a2434] hover:bg-amber-500 hover:text-slate-950 text-[#dee2ee] text-[10px] font-medium border border-[#232f42] transition btn-inspect-linked cursor-pointer">
                Inspect
              </button>
            </div>
          </td>
        `;

        const btnViewDoc = tr.querySelector('.btn-view-po-doc');
        if (btnViewDoc) {
          btnViewDoc.addEventListener('click', (e) => {
            e.stopPropagation();
            openDocumentViewer({
              invoiceId: inv.invoice_id,
              invoiceNo: inv.invoice_no_raw || inv.invoice_id,
              vendorName: inv.vendor_id,
              fileName: inv.file_name,
              filePath: inv.file_path,
            });
          });
        }

        const btnInspect = tr.querySelector('.btn-inspect-linked');
        if (btnInspect) {
          btnInspect.addEventListener('click', async (e) => {
            e.stopPropagation();
            currentInvoiceId = inv.invoice_id;
            showBreadcrumb('ws-pos', inv.invoice_no_raw || `#${inv.invoice_id}`);
            switchWorkspace('ws-single');
            const res = await fetch(`/api/invoices/${inv.invoice_id}`);
            const fullData = await res.json();
            await renderDecisionResult(fullData);
          });
        }

        invsTbody.appendChild(tr);
      });
    }
  }
}

/* ==========================================================================
   UNIVERSAL DOCUMENT VIEWER MODAL POPUP
   ========================================================================== */
function initDocumentViewerModal() {
  const modal = $('doc-viewer-modal');
  const btnClose = $('btn-modal-close');

  if (btnClose) {
    btnClose.addEventListener('click', closeDocumentViewer);
  }

  if (modal) {
    modal.addEventListener('click', (e) => {
      if (e.target === modal) {
        closeDocumentViewer();
      }
    });
  }

  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      const modal = $('doc-viewer-modal');
      if (modal && !modal.classList.contains('hidden')) {
        closeDocumentViewer();
      }
    }
  });
}

function closeDocumentViewer() {
  const modal = $('doc-viewer-modal');
  if (modal) {
    modal.classList.add('hidden');
    modal.setAttribute('aria-hidden', 'true');
  }
  const body = $('modal-doc-body');
  if (body) {
    body.innerHTML = '';
  }
  if (window.location.hash.includes('doc=1')) {
    if (window.history.length > 1) {
      window.history.back();
    } else if (currentInvoiceId) {
      AppRouter.navigate(`/cockpit/invoices/${currentInvoiceId}`, { replace: true });
    }
  }
}

async function openDocumentViewer({ invoiceId, invoiceNo, vendorName, fileName, filePath }) {
  const modal = $('doc-viewer-modal');
  if (!modal) return;

  if (invoiceId && !window.location.hash.includes('doc=1')) {
    AppRouter.navigate(`/cockpit/invoices/${invoiceId}?doc=1`);
  }

  const invDisplay = invoiceNo ? `#${invoiceNo}` : (invoiceId ? `#${invoiceId}` : 'Document');
  setText('modal-doc-title', `Invoice ${invDisplay}`);
  
  const displayFileName = fileName || (filePath ? filePath.split('/').pop() : 'document.pdf');
  setText('modal-doc-meta', `${vendorName || 'Vendor'} · ${displayFileName}`);

  const isImage = /\.(png|jpg|jpeg|webp)$/i.test(displayFileName);
  const badge = $('modal-doc-badge');
  if (badge) {
    badge.textContent = isImage ? 'IMAGE SCAN' : 'PDF DOCUMENT';
    badge.className = `badge ${isImage ? 'badge-amber' : ''}`;
  }

  const modalBody = $('modal-doc-body');
  if (modalBody) {
    modalBody.innerHTML = `
      <div class="doc-viewer-loading">
        <div class="spinner"></div>
        <span>Loading document preview...</span>
      </div>
    `;
  }

  modal.classList.remove('hidden');
  modal.setAttribute('aria-hidden', 'false');

  if (!invoiceId) {
    if (modalBody) {
      modalBody.innerHTML = `
        <div class="doc-fallback-card">
          <div class="doc-fallback-icon">📄</div>
          <h4>No Invoice Record Selected</h4>
          <p>Please select an invoice from the ledger to view its document.</p>
          <button class="btn btn-sm btn-primary" onclick="closeDocumentViewer()">Close Preview</button>
        </div>
      `;
    }
    return;
  }

  const fileUrl = `/api/invoices/${encodeURIComponent(invoiceId)}/file`;
  const btnTab = $('btn-modal-open-tab');
  const btnDown = $('btn-modal-download');
  if (btnTab) {
    btnTab.href = fileUrl;
    btnTab.target = '_blank';
  }
  if (btnDown) {
    btnDown.href = fileUrl;
    btnDown.download = displayFileName;
  }

  try {
    let checkRes;
    try {
      checkRes = await fetch(fileUrl, { method: 'HEAD' });
      if (!checkRes.ok && (checkRes.status === 405 || checkRes.status === 404)) {
        checkRes = await fetch(fileUrl, { headers: { Range: 'bytes=0-0' } });
      }
    } catch {
      checkRes = await fetch(fileUrl, { headers: { Range: 'bytes=0-0' } });
    }

    if (!checkRes.ok) {
      if (modalBody) {
        modalBody.innerHTML = `
          <div class="doc-fallback-card">
            <div class="doc-fallback-icon">📄</div>
            <h4>Physical Document Not Available on Disk</h4>
            <p>This invoice record was preloaded or generated as synthetic ledger data without an associated physical scan on disk.</p>
            <button class="btn btn-sm btn-primary" onclick="closeDocumentViewer()">Close Preview</button>
          </div>
        `;
      }
      return;
    }

    const contentType = checkRes.headers.get('content-type') || '';
    if (contentType.includes('pdf') || displayFileName.toLowerCase().endsWith('.pdf')) {
      modalBody.innerHTML = `
        <iframe src="${fileUrl}#toolbar=1&navpanes=0" class="doc-iframe w-full h-full" style="width: 100%; height: 100%; min-height: 100%; border: none;" title="Invoice PDF Preview"></iframe>
      `;
    } else {
      modalBody.innerHTML = `
        <div class="doc-image-container w-full h-full" style="width: 100%; height: 100%;">
          <img src="${fileUrl}" alt="Invoice Scan" class="doc-image">
        </div>
      `;
    }
  } catch (err) {
    if (modalBody) {
      modalBody.innerHTML = `
        <div class="doc-fallback-card">
          <div class="doc-fallback-icon">⚠️</div>
          <h4>Preview Load Error</h4>
          <p>${escapeHtml(err.message)}</p>
          <button class="btn btn-sm btn-primary" onclick="closeDocumentViewer()">Close</button>
        </div>
      `;
    }
  }
}


