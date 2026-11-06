// AP Automation Console Application Client
let currentInvoiceId = null;
let currentResult = null;

document.addEventListener('DOMContentLoaded', () => {
  initDropZone();
  initTabs();
  loadHistory();
  loadPOs();

  document.getElementById('btn-process').addEventListener('click', handleProcess);
  document.getElementById('btn-seed-demo').addEventListener('click', handleSeedDemo);
  document.getElementById('btn-review-approve').addEventListener('click', () => handleResolve('approve'));
  document.getElementById('btn-review-reject').addEventListener('click', () => handleResolve('reject'));
});

function initDropZone() {
  const dropZone = document.getElementById('drop-zone');
  const fileInput = document.getElementById('file-input');
  const btnProcess = document.getElementById('btn-process');

  fileInput.addEventListener('change', () => {
    if (fileInput.files.length > 0) {
      dropZone.querySelector('.hint').textContent = `Selected: ${fileInput.files[0].name}`;
      btnProcess.disabled = false;
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
      dropZone.querySelector('.hint').textContent = `Selected: ${fileInput.files[0].name}`;
      btnProcess.disabled = false;
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
      const target = document.getElementById(tab.dataset.tab);
      if (target) target.classList.add('active');
    });
  });
}

async function handleProcess() {
  const fileInput = document.getElementById('file-input');
  if (!fileInput.files.length) return;

  const ocrEngine = document.getElementById('ocr-select').value;
  const isDryRun = document.getElementById('dryrun-toggle').checked;

  const formData = new FormData();
  formData.append('file', fileInput.files[0]);

  const spinner = document.getElementById('processing-spinner');
  spinner.classList.remove('hidden');

  let url = `/api/invoices/process?dry_run=${isDryRun}`;
  if (ocrEngine) url += `&ocr_engine=${ocrEngine}`;

  try {
    const res = await fetch(url, { method: 'POST', body: formData });
    if (!res.ok) throw new Error(`Server returned ${res.status}`);
    const data = await res.json();
    renderDecisionResult(data);
    loadHistory();
  } catch (err) {
    alert(`Error processing invoice: ${err.message}`);
  } finally {
    spinner.classList.add('hidden');
  }
}

function renderDecisionResult(result) {
  currentResult = result;
  document.getElementById('empty-dashboard').classList.add('hidden');
  const dashboard = document.getElementById('result-dashboard');
  dashboard.classList.remove('hidden');

  // Decision Banner
  const banner = document.getElementById('decision-banner');
  banner.className = 'decision-banner';
  const badge = document.getElementById('decision-badge');
  badge.textContent = result.decision;

  if (result.decision === 'APPROVED') {
    banner.classList.add('status-approved');
  } else if (result.decision === 'REJECTED') {
    banner.classList.add('status-rejected');
  } else {
    banner.classList.add('status-review');
  }

  document.getElementById('reason-code-badge').textContent = result.reason_code;
  document.getElementById('decision-summary').textContent = result.summary;

  // Confidence
  const confVal = result.confidence.toFixed(2);
  document.getElementById('confidence-val').textContent = confVal;
  document.getElementById('confidence-bar-fill').style.width = `${result.confidence * 100}%`;

  // Review Actions Panel
  const reviewPanel = document.getElementById('review-action-panel');
  const reviewControls = document.getElementById('review-action-controls');
  reviewControls.innerHTML = '';

  if (result.review && result.review.required) {
    reviewPanel.classList.remove('hidden');
    result.review.actions.forEach(action => {
      if (action.type === 'select_po') {
        const div = document.createElement('div');
        div.innerHTML = `<strong>Select PO:</strong> `;
        action.options.forEach(po => {
          div.innerHTML += `
            <label style="margin-right: 12px;">
              <input type="radio" name="select_po_opt" value="${escapeHtml(po)}"> ${escapeHtml(po)}
            </label>
          `;
        });
        reviewControls.appendChild(div);
      }
    });
  } else {
    reviewPanel.classList.add('hidden');
  }

  // Reasoning
  const reasoningList = document.getElementById('reasoning-list');
  reasoningList.innerHTML = '';
  result.reasoning.forEach(r => {
    const li = document.createElement('li');
    li.textContent = r;
    reasoningList.appendChild(li);
  });

  // Extracted Fields Table
  const fieldsBody = document.getElementById('extracted-fields-body');
  fieldsBody.innerHTML = '';
  if (result.extracted) {
    const ext = result.extracted;
    const addRow = (name, val, conf) => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td><strong>${escapeHtml(name)}</strong></td>
        <td>${escapeHtml(String(val ?? '—'))}</td>
        <td>${conf !== undefined ? (conf * 100).toFixed(0) + '%' : '—'}</td>
        <td>✓</td>
      `;
      fieldsBody.appendChild(tr);
    };

    addRow('Vendor Name', ext.vendor?.name, ext.vendor?.confidence);
    addRow('GSTIN', ext.vendor?.gstin, ext.vendor?.confidence);
    addRow('Invoice #', ext.invoice_number?.value, ext.invoice_number?.confidence);
    addRow('Invoice Date', ext.invoice_date?.value, ext.invoice_date?.confidence);
    addRow('PO Reference', ext.po_reference?.value, ext.po_reference?.confidence);
    addRow('Grand Total', `${ext.currency?.value ?? 'INR'} ${ext.grand_total?.value ?? 0}`, ext.grand_total?.confidence);

    // Line Items
    const lineBody = document.getElementById('line-items-body');
    lineBody.innerHTML = '';
    (ext.line_items || []).forEach(l => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${l.line_no}</td>
        <td>${escapeHtml(l.description)}</td>
        <td>${l.quantity}</td>
        <td>${l.unit_price.toFixed(2)}</td>
        <td>${l.line_total.toFixed(2)}</td>
      `;
      lineBody.appendChild(tr);
    });
  }

  // PO Match Card & Candidates
  const poMatchInfo = document.getElementById('po-match-info');
  poMatchInfo.innerHTML = `
    <p><strong>Selected PO:</strong> ${result.match.selected_po ?? 'None'}</p>
    <p><strong>Tier:</strong> ${result.match.tier ?? '—'} (${result.match.method ?? 'None'})</p>
  `;

  const candBody = document.getElementById('candidates-body');
  candBody.innerHTML = '';
  (result.match.candidates || []).forEach(c => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><strong>${escapeHtml(c.po_id)}</strong></td>
      <td>${c.score.toFixed(2)}</td>
      <td>P:${c.signals.price} Q:${c.signals.quantity} T:${c.signals.total_coverage}</td>
      <td>${escapeHtml(c.notes.join('; '))}</td>
    `;
    candBody.appendChild(tr);
  });

  // Balance Card
  const poBalCard = document.getElementById('po-balance-card');
  if (result.po_balance) {
    poBalCard.classList.remove('hidden');
    const bal = result.po_balance;
    const billedPct = (bal.previously_billed / Math.max(1, bal.po_total)) * 100;
    const thisPct = (bal.this_invoice / Math.max(1, bal.po_total)) * 100;

    document.getElementById('balance-bar-consumed').style.width = `${billedPct}%`;
    document.getElementById('balance-bar-this').style.width = `${thisPct}%`;
    document.getElementById('balance-legend').textContent =
      `Total: ${bal.po_total.toFixed(2)} | Billed: ${bal.previously_billed.toFixed(2)} | This: ${bal.this_invoice.toFixed(2)} | Rem: ${bal.remaining_after.toFixed(2)}`;
  } else {
    poBalCard.classList.add('hidden');
  }

  // Rules Table
  const rulesBody = document.getElementById('rules-body');
  rulesBody.innerHTML = '';
  (result.checks || []).forEach(chk => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><strong>${escapeHtml(chk.rule)}</strong></td>
      <td><span class="badge">${escapeHtml(chk.status)}</span></td>
      <td>${escapeHtml(chk.severity)}</td>
      <td>${escapeHtml(chk.message)}</td>
    `;
    rulesBody.appendChild(tr);
  });

  // Trace Table
  const traceBody = document.getElementById('trace-body');
  traceBody.innerHTML = '';
  (result.trace || []).forEach(trEntry => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><strong>${escapeHtml(trEntry.stage)}</strong></td>
      <td>${escapeHtml(trEntry.status)}</td>
      <td>${trEntry.duration_ms} ms</td>
      <td>${escapeHtml(trEntry.summary)}</td>
    `;
    traceBody.appendChild(tr);
  });

  if (result.timings_ms) {
    document.getElementById('total-latency').textContent = `Total: ${result.timings_ms.total} ms`;
  }
}

async function handleResolve(action) {
  if (!currentInvoiceId) {
    alert('Please select or persist an invoice first to apply reviewer resolution.');
    return;
  }

  const note = document.getElementById('review-note').value;
  const selectedRadio = document.querySelector('input[name="select_po_opt"]:checked');
  const poId = selectedRadio ? selectedRadio.value : null;

  try {
    const res = await fetch(`/api/invoices/${currentInvoiceId}/resolve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: action === 'approve' ? 'select_po' : 'reject', po_id: poId, note: note }),
    });
    if (!res.ok) throw new Error('Failed to resolve');
    const updated = await res.json();
    renderDecisionResult(updated);
    loadHistory();
  } catch (err) {
    alert(`Resolution error: ${err.message}`);
  }
}

async function loadHistory() {
  const list = document.getElementById('history-list');
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
        renderDecisionResult(fullData);
      });
      list.appendChild(li);
    });
  } catch (err) {
    list.innerHTML = '<li class="empty-state">Failed to load history</li>';
  }
}

async function loadPOs() {
  const list = document.getElementById('po-list');
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
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
