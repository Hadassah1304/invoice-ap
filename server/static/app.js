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

document.addEventListener('DOMContentLoaded', () => {
  initDropZone();
  initTabs();
  initRuleFilters();
  loadHistory();
  loadPOs();

  const btnProcess = $('btn-process');
  if (btnProcess) btnProcess.addEventListener('click', handleProcess);

  const btnSeed = $('btn-seed-demo');
  if (btnSeed) btnSeed.addEventListener('click', handleSeedDemo);

  const btnApprove = $('btn-review-approve');
  if (btnApprove) btnApprove.addEventListener('click', () => handleResolve('approve'));

  const btnReject = $('btn-review-reject');
  if (btnReject) btnReject.addEventListener('click', () => handleResolve('reject'));
});

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
      tabs.forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));

      tab.classList.add('active');
      const target = $(tab.dataset.tab);
      if (target) target.classList.add('active');
    });
  });
}

function initRuleFilters() {
  const filterBtns = document.querySelectorAll('.rule-filter-btn');
  filterBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      filterBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      activeRuleFilter = btn.dataset.filter;
      if (currentResult && currentResult.checks) {
        renderRules(currentResult.checks, activeRuleFilter);
      }
    });
  });
}

async function handleProcess() {
  const fileInput = $('file-input');
  if (!fileInput || !fileInput.files.length) return;

  const ocrEngine = $('ocr-select') ? $('ocr-select').value : '';
  const isDryRun = $('dryrun-toggle') ? $('dryrun-toggle').checked : false;

  const formData = new FormData();
  formData.append('file', fileInput.files[0]);

  const spinner = $('processing-spinner');
  if (spinner) spinner.classList.remove('hidden');

  let url = `/api/invoices/process?dry_run=${isDryRun}`;
  if (ocrEngine) url += `&ocr_engine=${ocrEngine}`;

  try {
    const res = await fetch(url, { method: 'POST', body: formData });
    if (!res.ok) throw new Error(`Server returned ${res.status}`);
    const data = await res.json();
    await renderDecisionResult(data);
    loadHistory();
  } catch (err) {
    alert(`Error processing invoice: ${err.message}`);
  } finally {
    if (spinner) spinner.classList.add('hidden');
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
  currentResult = result;

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

  setText('decision-badge', result.decision || 'UNKNOWN');
  setText('reason-code-badge', result.reason_code || 'OK');
  setText('decision-summary', result.summary || '');

  // Confidence Widget with 3-tier colors
  const confVal = typeof result.confidence === 'number' ? result.confidence : 0;
  const confTier = getConfidenceTier(confVal);
  setText('confidence-val', confVal.toFixed(2));

  const tierPill = $('confidence-tier-pill');
  if (tierPill) {
    tierPill.textContent = `${confTier.label} (${Math.round(confVal * 100)}%)`;
    tierPill.className = `confidence-tier-pill tier-${confTier.tier}`;
  }

  const barFill = $('confidence-bar-fill');
  if (barFill) {
    barFill.style.width = `${Math.min(100, Math.max(0, confVal * 100))}%`;
    barFill.style.backgroundColor = confTier.barColor;
  }

  // Active PO Determination
  activePOId = result.match?.selected_po || (result.match?.candidates?.[0]?.po_id ?? null);

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
  renderSideBySide(result, activePOId, poDetail);

  // PO Balance Consumption Card
  renderBalanceCard(result.po_balance, result.extracted?.currency?.value || 'INR');

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
      poEl.className = 'snapshot-val po-pill pill-green';
      poEl.style.background = '#dcfce7';
      poEl.style.color = '#15803d';
      poEl.style.borderColor = '#86efac';
    } else if (result.decision === 'REJECTED') {
      poEl.textContent = 'STATUS: REJECTED';
      poEl.className = 'snapshot-val po-pill';
      poEl.style.background = '#fee2e2';
      poEl.style.color = '#b91c1c';
      poEl.style.borderColor = '#fca5a5';
    } else {
      if (candidates.length > 1) {
        poEl.textContent = `REVIEWING: ${currentPoId || 'CANDIDATE'} (${candidates.length} CANDIDATES)`;
        poEl.className = 'snapshot-val po-pill';
        poEl.style.background = '#fef3c7';
        poEl.style.color = '#b45309';
        poEl.style.borderColor = '#fde68a';
      } else if (currentPoId) {
        poEl.textContent = `CANDIDATE: ${currentPoId}`;
        poEl.className = 'snapshot-val po-pill';
        poEl.style.background = '#eff6ff';
        poEl.style.color = '#1e40af';
        poEl.style.borderColor = '#bfdbfe';
      } else {
        poEl.textContent = 'NO PO MATCHED';
        poEl.className = 'snapshot-val po-pill';
        poEl.style.background = '#f1f5f9';
        poEl.style.color = '#475569';
        poEl.style.borderColor = '#cbd5e1';
      }
    }
  }
}

function renderSideBySide(result, targetPoId, poDetail) {
  const ext = result.extracted || {};
  setText('active-po-label', targetPoId || 'None Selected');
  setText('reconcile-po-id', targetPoId ? `PO: ${targetPoId}` : 'No Active PO');

  const curr = ext.currency?.value || 'INR';
  const invVendor = ext.vendor?.name || '—';
  const invGstin = ext.vendor?.gstin || 'Not Provided';
  const invTotal = ext.grand_total?.value != null ? Number(ext.grand_total.value) : 0;
  const invDate = ext.invoice_date?.value || '—';

  // Find candidate matching info for active PO
  const candidate = (result.match?.candidates || []).find(c => c.po_id === targetPoId);

  // 1. Vendor Alignment
  const poVendor = poDetail?.vendor?.name || poDetail?.po?.vendor_id || (targetPoId ? 'Catalog Master' : '—');
  const poGstin = poDetail?.vendor?.gstin || '—';
  setText('diff-inv-vendor', invVendor);
  setText('diff-inv-gstin', invGstin !== 'Not Provided' ? `GSTIN: ${invGstin}` : 'GSTIN: Not Available');
  setText('diff-po-vendor', poVendor);
  setText('diff-po-gstin', poGstin !== '—' ? `GSTIN: ${poGstin}` : 'GSTIN: Not Recorded');

  const vStatus = $('diff-vendor-status');
  const vSub = $('diff-vendor-sub');
  if (vStatus) {
    if (!targetPoId) {
      vStatus.className = 'diff-status-pill status-neutral';
      vStatus.textContent = 'NO PO LINKED';
      if (vSub) vSub.textContent = 'Select a purchase order to verify vendor';
    } else if (poGstin !== '—' && invGstin !== 'Not Provided' && invGstin.toUpperCase() === poGstin.toUpperCase()) {
      vStatus.className = 'diff-status-pill status-match';
      vStatus.textContent = 'EXACT GSTIN MATCH';
      if (vSub) vSub.textContent = 'Tax ID and vendor entity verified with master record';
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

  // 3. Order Value & Coverage Alignment (Clear Partial Billing Context)
  const poTotal = poDetail?.po?.total != null ? Number(poDetail.po.total) : null;
  setText('diff-inv-total', `${curr} ${invTotal.toLocaleString(undefined, { minimumFractionDigits: 2 })}`);
  setText('diff-po-total', poTotal != null ? `${curr} ${poTotal.toLocaleString(undefined, { minimumFractionDigits: 2 })}` : '—');

  const invTotalSub = $('diff-inv-total-sub');
  const poTotalSub = $('diff-po-total-sub');
  const tStatus = $('diff-total-status');
  const tSub = $('diff-total-sub');
  const barContainer = $('diff-coverage-bar-container');
  const barFill = $('diff-coverage-bar-fill');

  if (poTotal != null && poTotal > 0) {
    const diff = invTotal - poTotal;
    const billedPct = (invTotal / poTotal) * 100;
    const remainingAfter = poTotal - invTotal;

    if (barContainer) barContainer.classList.remove('hidden');

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
      if (tSub) tSub.textContent = `Invoice completes 100% of the total PO commitment (${curr} ${poTotal.toLocaleString(undefined, { minimumFractionDigits: 2 })}).`;
    } else if (diff < 0) {
      if (invTotalSub) invTotalSub.textContent = `Current Invoice Claim (Partial · ${billedPct.toFixed(0)}%)`;
      if (poTotalSub) poTotalSub.textContent = `Total PO Lifetime Commitment (${curr} ${remainingAfter.toLocaleString(undefined, { minimumFractionDigits: 2 })} remaining)`;
      if (tStatus) {
        tStatus.className = 'diff-status-pill status-partial';
        tStatus.textContent = `PARTIAL BILLING · ${billedPct.toFixed(0)}% COVERAGE`;
      }
      if (barFill) {
        barFill.style.width = `${Math.min(100, Math.max(0, billedPct))}%`;
        barFill.className = 'recon-progress-fill';
      }
      if (tSub) tSub.textContent = `Covers ${billedPct.toFixed(0)}% of PO allocation. Normal partial milestone with ${curr} ${remainingAfter.toLocaleString(undefined, { minimumFractionDigits: 2 })} remaining headroom.`;
    } else {
      const overrunPct = ((diff / poTotal) * 100).toFixed(1);
      if (invTotalSub) invTotalSub.textContent = 'Current Claim (Exceeds PO Allocation)';
      if (poTotalSub) poTotalSub.textContent = `Total PO Commitment (Deficit: -${curr} ${diff.toFixed(2)})`;
      if (tStatus) {
        tStatus.className = 'diff-status-pill status-drift';
        tStatus.textContent = `BUDGET OVERRUN · +${overrunPct}%`;
      }
      if (barFill) {
        barFill.style.width = '100%';
        barFill.className = 'recon-progress-fill fill-red';
      }
      if (tSub) tSub.textContent = `Exceeds total PO allocation by +${curr} ${diff.toLocaleString(undefined, { minimumFractionDigits: 2 })} (${overrunPct}% overrun).`;
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

  // 4. Line Items Comparison Widgets (Paired Two-Row Layout per Item, No Emojis)
  const widgetsContainer = $('line-items-widgets-container');
  if (!widgetsContainer) return;
  widgetsContainer.innerHTML = '';

  const invLines = ext.line_items || [];
  const poItems = poDetail?.items || [];
  const lineMatches = candidate?.line_matches || [];

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
        deltaChips.push(`<span class="delta-chip ${chipClass}">RATE VARIANCE: ${sign}${curr} ${priceDiff.toFixed(2)} (${sign}${driftPct}%)</span>`);
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
          deltaChips.push(`<span class="delta-chip delta-warn">LINE TOTAL DELTA: ${sign}${curr} ${totDiff.toFixed(2)}</span>`);
        }
      }
    }

    const widget = document.createElement('div');
    widget.className = 'item-widget';
    widget.innerHTML = `
      <div class="item-widget-header">
        <div class="item-widget-title">
          <span class="item-line-no">Item #${invLine.line_no ?? (idx + 1)}</span>
          <span class="item-main-desc">${escapeHtml(invLine.description)}</span>
        </div>
        ${overallBadgeHtml}
      </div>

      <div class="item-widget-grid">
        <!-- Row 1: Invoice Claim -->
        <div class="item-row item-row-invoice">
          <div><span class="badge-source badge-inv">INVOICE</span></div>
          <div class="item-cell-desc">
            ${escapeHtml(invLine.description)}
          </div>
          <div class="item-cell-stat">
            <span class="stat-lbl">Billed Qty</span>
            <span class="stat-val">${invLine.quantity ?? '—'} ${escapeHtml(invLine.uom || '')}</span>
          </div>
          <div class="item-cell-stat">
            <span class="stat-lbl">Invoice Rate</span>
            <span class="stat-val">${curr} ${(invLine.unit_price ?? 0).toFixed(2)}</span>
          </div>
          <div class="item-cell-stat stat-total">
            <span class="stat-lbl">Invoice Total</span>
            <span class="stat-val">${curr} ${iTot.toFixed(2)}</span>
          </div>
        </div>

        <!-- Row 2: Matched PO Specification -->
        <div class="item-row item-row-po">
          <div><span class="badge-source badge-po">PO MASTER</span></div>
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
            <span class="stat-val">${poItem ? `${curr} ${Number(poItem.unit_price).toFixed(2)}` : '—'}</span>
          </div>
          <div class="item-cell-stat stat-total">
            <span class="stat-lbl">PO Line Total</span>
            <span class="stat-val">${pTot != null ? `${curr} ${pTot.toFixed(2)}` : '—'}</span>
          </div>
        </div>
      </div>

      ${deltaChips.length > 0 ? `
        <div class="item-delta-strip">
          ${deltaChips.join('')}
        </div>
      ` : ''}
    `;

    widgetsContainer.appendChild(widget);
  });
}

function renderBalanceCard(bal, curr) {
  const card = $('po-balance-card');
  if (!card) return;
  if (!bal) {
    card.classList.add('hidden');
    return;
  }
  card.classList.remove('hidden');

  const total = Number(bal.po_total) || 0;
  const billed = Number(bal.previously_billed) || 0;
  const thisInv = Number(bal.this_invoice) || 0;
  const remaining = Number(bal.remaining_after) || 0;

  const billedPct = total > 0 ? (billed / total) * 100 : 0;
  const thisPct = total > 0 ? (thisInv / total) * 100 : 0;
  const remPct = total > 0 ? Math.max(0, (remaining / total) * 100) : 0;

  setText('kpi-po-total', `${curr} ${total.toLocaleString(undefined, { minimumFractionDigits: 2 })}`);
  setText('kpi-po-billed', `${curr} ${billed.toLocaleString(undefined, { minimumFractionDigits: 2 })}`);
  setText('kpi-po-billed-pct', `${billedPct.toFixed(1)}% drawn previously`);
  setText('kpi-po-this', `${curr} ${thisInv.toLocaleString(undefined, { minimumFractionDigits: 2 })}`);
  setText('kpi-po-this-pct', `${thisPct.toFixed(1)}% of total commitment`);
  setText('kpi-po-rem', `${curr} ${remaining.toLocaleString(undefined, { minimumFractionDigits: 2 })}`);

  const remCard = $('kpi-remaining-card');
  const remStatusEl = $('kpi-po-rem-status');
  const healthPill = $('balance-health-pill');

  if (remCard) {
    remCard.className = 'balance-kpi-card highlight-remaining';
    if (remaining < 0) {
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
    tr.className = `candidate-row ${isSelected ? 'selected-po-row' : ''}`;
    tr.title = 'Click to preview side-by-side comparison for this PO';
    tr.innerHTML = `
      <td>
        <span class="po-id-pill">${escapeHtml(c.po_id)}</span>
        ${isSelected ? '<span class="badge" style="margin-left: 4px; font-size: 0.68rem; background: #2563eb; color: white;">Selected</span>' : ''}
      </td>
      <td>
        <div class="fit-pill">
          <span class="conf-badge ${scoreTier.cssClass}">${scorePct}% Match</span>
          <span class="fit-label">${fitText}</span>
        </div>
      </td>
      <td>${signalsHtml}</td>
      <td>${notesHtml}</td>
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

  const addRow = (name, val, conf) => {
    const tr = document.createElement('tr');
    let confHtml = '—';
    if (conf !== undefined && conf !== null) {
      const tier = getConfidenceTier(conf);
      confHtml = `<span class="conf-badge ${tier.cssClass}">${(Number(conf) * 100).toFixed(0)}%</span>`;
    }

    tr.innerHTML = `
      <td><strong>${escapeHtml(name)}</strong></td>
      <td>${escapeHtml(String(val ?? '—'))}</td>
      <td>${confHtml}</td>
      <td style="color: #16a34a; font-weight: 700;">OK</td>
    `;
    fieldsBody.appendChild(tr);
  };

  addRow('Vendor Name', ext.vendor?.name, ext.vendor?.confidence);
  addRow('GSTIN', ext.vendor?.gstin, ext.vendor?.confidence);
  addRow('Invoice #', ext.invoice_number?.value, ext.invoice_number?.confidence);
  addRow('Invoice Date', ext.invoice_date?.value, ext.invoice_date?.confidence);
  addRow('PO Reference', ext.po_reference?.value, ext.po_reference?.confidence);
  addRow('Currency', ext.currency?.value, ext.currency?.confidence);
  addRow('Total Invoiced', `${ext.currency?.value ?? 'INR'} ${ext.grand_total?.value ?? 0}`, ext.grand_total?.confidence);
}

function renderReasoning(reasons) {
  const reasoningList = $('reasoning-list');
  if (!reasoningList) return;
  reasoningList.innerHTML = '';

  if (!reasons || !reasons.length) {
    reasoningList.innerHTML = '<li class="empty-state">No reasoning chain generated</li>';
    return;
  }

  reasons.forEach(r => {
    const lower = String(r).toLowerCase();
    let badgeLabel = 'INFO';
    let borderTint = '#f1f5f9';
    let badgeColor = '#475569';
    let badgeBg = '#f1f5f9';

    if (lower.includes('approved') || lower.includes('pass') || lower.includes('exact') || lower.includes('valid') || lower.includes('healthy')) {
      badgeLabel = 'PASSED';
      borderTint = '#dcfce7';
      badgeColor = '#15803d';
      badgeBg = '#dcfce7';
    } else if (lower.includes('review') || lower.includes('drift') || lower.includes('ambiguous') || lower.includes('warn') || lower.includes('caution')) {
      badgeLabel = 'ATTENTION';
      borderTint = '#fef3c7';
      badgeColor = '#b45309';
      badgeBg = '#fef3c7';
    } else if (lower.includes('reject') || lower.includes('fail') || lower.includes('duplicate') || lower.includes('closed') || lower.includes('over')) {
      badgeLabel = 'FLAGGED';
      borderTint = '#fee2e2';
      badgeColor = '#b91c1c';
      badgeBg = '#fee2e2';
    }

    const li = document.createElement('li');
    li.className = 'reasoning-item';
    li.style.borderColor = borderTint;
    li.innerHTML = `
      <span class="badge" style="background: ${badgeBg}; color: ${badgeColor}; font-size: 0.68rem; font-weight: 700; align-self: flex-start;">${badgeLabel}</span>
      <span>${escapeHtml(r)}</span>
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

  const filtered = (checks || []).filter(chk => {
    if (filter === 'exceptions') return chk.status !== 'PASS';
    if (filter === 'passed') return chk.status === 'PASS';
    return true;
  });

  if (!filtered.length) {
    rulesBody.innerHTML = `<tr><td colspan="4" class="empty-state">No rules matching filter "${escapeHtml(filter)}"</td></tr>`;
    return;
  }

  filtered.forEach(chk => {
    let statusClass = 'badge-rule-pass';
    const st = (chk.status || '').toUpperCase();
    if (st === 'FAIL' || st === 'BLOCK' || st === 'REJECT') {
      statusClass = 'badge-rule-fail';
    } else if (st === 'WARN' || st === 'FLAG' || st === 'REVIEW') {
      statusClass = 'badge-rule-warn';
    } else {
      statusClass = 'badge-rule-pass';
    }

    let sevClass = 'badge-severity-info';
    const s = (chk.severity || '').toUpperCase();
    if (s === 'REJECT' || s === 'HARD' || s === 'BLOCK' || s === 'ERROR') {
      sevClass = 'badge-severity-reject';
    } else if (s === 'REVIEW') {
      sevClass = 'badge-severity-review';
    } else if (s === 'WARN' || s === 'SOFT' || s === 'FLAG') {
      sevClass = 'badge-severity-warn';
    } else {
      sevClass = 'badge-severity-info';
    }

    let rowClass = '';
    if (st === 'FAIL' || st === 'BLOCK' || st === 'REJECT') {
      rowClass = 'rule-row-fail';
    } else if (st === 'WARN' || st === 'FLAG' || st === 'REVIEW') {
      rowClass = 'rule-row-warn';
    }

    const tr = document.createElement('tr');
    if (rowClass) tr.className = rowClass;
    tr.innerHTML = `
      <td><strong>${escapeHtml(chk.rule)}</strong></td>
      <td><span class="badge ${statusClass}">${escapeHtml(chk.status)}</span></td>
      <td><span class="badge ${sevClass}">${escapeHtml(chk.severity)}</span></td>
      <td>${escapeHtml(chk.message)}</td>
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
    tr.innerHTML = `
      <td><strong>${escapeHtml(trEntry.stage)}</strong></td>
      <td><span class="badge" style="font-size: 0.7rem;">${escapeHtml(trEntry.status)}</span></td>
      <td>${trEntry.duration_ms} ms</td>
      <td>${escapeHtml(trEntry.summary)}</td>
    `;
    traceBody.appendChild(tr);
  });

  if (timings && timings.total != null) {
    setText('total-latency', `Total Pipeline: ${timings.total} ms`);
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
    await renderDecisionResult(updated);
    loadHistory();
  } catch (err) {
    alert(`Resolution error: ${err.message}`);
  }
}

async function loadHistory() {
  const list = $('history-list');
  if (!list) return;
  try {
    const res = await fetch('/api/invoices');
    const items = await res.json();
    list.innerHTML = '';
    if (!items.length) {
      list.innerHTML = '<li class="empty-state">No processed invoices yet</li>';
      return;
    }
    items.forEach(inv => {
      const li = document.createElement('li');
      li.className = 'history-item';
      li.innerHTML = `
        <div><strong>#${escapeHtml(inv.invoice_no_raw || 'N/A')}</strong> — ${inv.vendor_id || 'Unknown'}</div>
        <div class="hint">${escapeHtml(inv.status)} | Total: ${inv.total ?? '—'}</div>
      `;
      li.addEventListener('click', async () => {
        currentInvoiceId = inv.invoice_id;
        const detailRes = await fetch(`/api/invoices/${inv.invoice_id}`);
        const fullData = await detailRes.json();
        await renderDecisionResult(fullData);
      });
      list.appendChild(li);
    });
  } catch (err) {
    list.innerHTML = '<li class="empty-state">Failed to load history</li>';
  }
}

async function loadPOs() {
  const list = $('po-list');
  if (!list) return;
  try {
    const res = await fetch('/api/pos');
    const pos = await res.json();
    list.innerHTML = '';
    pos.forEach(po => {
      const li = document.createElement('li');
      li.className = 'po-item';
      li.innerHTML = `
        <div><strong>${escapeHtml(po.po_id)}</strong> (${escapeHtml(po.status)})</div>
        <div class="hint">Vendor: ${escapeHtml(po.vendor_id)} | Total: ${po.total}</div>
      `;
      list.appendChild(li);
    });
  } catch (err) {
    list.innerHTML = '<li class="empty-state">Failed to load POs</li>';
  }
}

async function handleSeedDemo() {
  try {
    const res = await fetch('/api/health');
    alert('Demo database is ready and loaded from samples/seed.json.');
    loadPOs();
    loadHistory();
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
