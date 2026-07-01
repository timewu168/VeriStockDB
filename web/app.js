const DATASET_LABELS = {
  daily_close: "Close",
  attention_notice: "注意公告",
  disposal_notice: "處置公告",
  legal_investor: "法人",
  margin: "資券",
  day_trading: "當沖",
  revenue: "月營收",
};

const UPDATE_HINTS = {
  daily_close: "update-close",
  attention_notice: "update-attention",
  disposal_notice: "update-disposal",
  legal_investor: "update-legal",
  margin: "update-margin",
  day_trading: "update-day-trading",
  revenue: "update-revenue",
};

const pageTitles = {
  dashboard: ["總覽", "本地真理資料庫狀態與排程更新摘要"],
  datasets: ["資料集狀態", "檢查最新資料、問題批次，必要時手動重新更新"],
  batches: ["批次紀錄", "查看 import_batches 狀態與最近更新結果"],
  events: ["錯誤事件", "查看 import_errors 與 data_events"],
  query: ["查詢", "使用 Local Truth API 查詢正式資料"],
  system: ["系統", "版本、API 與本機 PWA 設定"],
};

const state = {
  datasets: [],
  statuses: new Map(),
  pendingDataset: null,
  jobPollTimer: null,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

document.addEventListener("DOMContentLoaded", () => {
  bindNavigation();
  bindActions();
  loadToken();
  refreshAll();
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/service-worker.js").catch(() => {});
  }
});

function bindNavigation() {
  [...$$(".nav-item"), ...$$(".bottom-item")].forEach((button) => {
    button.addEventListener("click", () => showView(button.dataset.view));
  });
  $$("[data-jump]").forEach((button) => {
    button.addEventListener("click", () => showView(button.dataset.jump));
  });
}

function bindActions() {
  $("#refresh-view").addEventListener("click", refreshCurrentView);
  $("#reload-batches").addEventListener("click", loadBatches);
  $("#reload-errors").addEventListener("click", loadErrors);
  $("#reload-events").addEventListener("click", loadEvents);
  $("#cancel-update").addEventListener("click", closeUpdateModal);
  $("#confirm-update").addEventListener("click", startUpdateJob);
  $("#close-job").addEventListener("click", () => {
    $("#job-drawer").hidden = true;
  });
  $("#save-token").addEventListener("click", () => {
    localStorage.setItem("veristock_api_token", $("#api-token").value.trim());
    refreshAll();
  });
  $("#query-form").addEventListener("submit", runQuery);
}

function showView(view) {
  $$(".view").forEach((node) => node.classList.toggle("active", node.id === `view-${view}`));
  [...$$(".nav-item"), ...$$(".bottom-item")].forEach((node) => {
    node.classList.toggle("active", node.dataset.view === view);
  });
  const [title, subtitle] = pageTitles[view] || pageTitles.dashboard;
  $("#page-title").textContent = title;
  $("#page-subtitle").textContent = subtitle;
}

function refreshCurrentView() {
  const active = $(".view.active")?.id?.replace("view-", "") || "dashboard";
  if (active === "datasets") loadDatasets();
  else if (active === "batches") loadBatches();
  else if (active === "events") {
    loadErrors();
    loadEvents();
  } else refreshAll();
}

async function refreshAll() {
  await Promise.allSettled([loadInfo(), loadDatasets(), loadBatches(), loadErrors(), loadEvents(), loadJobs()]);
}

async function loadInfo() {
  try {
    const health = await api("/health", { raw: true });
    const info = await api("/api/v1/info");
    $("#api-status").textContent = "API OK";
    $("#api-status").className = "status-chip ok";
    $("#metric-api").textContent = "OK";
    $("#metric-api-detail").textContent = health.status || "healthy";
    $("#version-chip").textContent = `v${info.data.app_version}`;
    $("#system-info").innerHTML = `
      <dt>App</dt><dd>${escapeHtml(info.data.app_name)}</dd>
      <dt>Version</dt><dd>${escapeHtml(info.data.app_version)}</dd>
      <dt>Schema</dt><dd>${escapeHtml(info.data.schema_version)}</dd>
      <dt>API</dt><dd>${escapeHtml(info.data.api_version)}</dd>
      <dt>Mode</dt><dd>${escapeHtml(info.data.mode)}</dd>
    `;
  } catch (error) {
    $("#api-status").textContent = "API ERROR";
    $("#api-status").className = "status-chip error";
    $("#metric-api").textContent = "ERROR";
    $("#metric-api-detail").textContent = error.message;
  }
}

async function loadDatasets() {
  try {
    const [datasetsResponse, statusResponse] = await Promise.all([
      api("/api/v1/datasets"),
      api("/api/v1/datasets/status-summary"),
    ]);
    state.datasets = datasetsResponse.data;
    state.statuses = new Map(statusResponse.data.map((row) => [row.dataset, row]));
    renderDatasets();
  } catch (error) {
    $("#dataset-table").innerHTML = rowMessage(`讀取資料集失敗：${escapeHtml(error.message)}`, 5);
  }
}

function renderDatasets() {
  $("#metric-datasets").textContent = String(state.datasets.length);
  const rows = state.datasets.map((dataset) => {
    const status = state.statuses.get(dataset.dataset) || {};
    const quality = status.quality?.status || "UNKNOWN";
    const problems = status.quality?.problem_batches ?? 0;
    const canUpdate = UPDATE_HINTS[dataset.dataset];
    return `
      <tr>
        <td>
          <strong>${labelDataset(dataset.dataset)}</strong>
          <div class="subtle">${escapeHtml(dataset.dataset)}</div>
        </td>
        <td>${escapeHtml(status.latest_period || "-")}</td>
        <td>${pill(quality)}</td>
        <td>${problems}</td>
        <td>
          ${
            canUpdate
              ? `<button class="text-button" data-update="${escapeHtml(dataset.dataset)}" title="手動執行 ${escapeHtml(canUpdate)}">↻ 更新</button>`
              : `<span class="muted">-</span>`
          }
        </td>
      </tr>
    `;
  });
  $("#dataset-table").innerHTML = rows.join("") || rowMessage("沒有資料集", 5);
  $("#dashboard-datasets").innerHTML = state.datasets
    .slice(0, 8)
    .map((dataset) => {
      const status = state.statuses.get(dataset.dataset) || {};
      return `
        <div class="list-row">
          <div>
            <strong>${labelDataset(dataset.dataset)}</strong>
            <span>${escapeHtml(status.latest_period || "-")}</span>
          </div>
          ${pill(status.quality?.status || "UNKNOWN")}
        </div>
      `;
    })
    .join("");
  $$("[data-update]").forEach((button) => {
    button.addEventListener("click", () => openUpdateModal(button.dataset.update));
  });
}

async function loadBatches() {
  try {
    const response = await api("/api/v1/batches?limit=20");
    $("#batch-table").innerHTML = response.data.map(renderBatchRow).join("") || rowMessage("沒有批次紀錄", 6);
    $("#dashboard-batches").innerHTML = response.data.slice(0, 6).map(renderBatchCompact).join("") || `<div class="list-row"><span>沒有批次紀錄</span></div>`;
  } catch (error) {
    $("#batch-table").innerHTML = rowMessage(`讀取批次失敗：${escapeHtml(error.message)}`, 6);
  }
}

function renderBatchRow(batch) {
  return `
    <tr>
      <td>${escapeHtml(batch.period || "-")}</td>
      <td>${labelDataset(batch.dataset)}</td>
      <td>${escapeHtml(batch.market || "-")}</td>
      <td>${pill(batch.status)}</td>
      <td>${batch.row_count ?? "-"}</td>
      <td>${escapeHtml(batch.checked_at || "-")}</td>
    </tr>
  `;
}

function renderBatchCompact(batch) {
  return `
    <div class="list-row">
      <div>
        <strong>${labelDataset(batch.dataset)} · ${escapeHtml(batch.period || "-")}</strong>
        <span>${escapeHtml(batch.market || "-")} · rows ${batch.row_count ?? "-"}</span>
      </div>
      ${pill(batch.status)}
    </div>
  `;
}

async function loadErrors() {
  try {
    const response = await api("/api/v1/errors?limit=12");
    $("#metric-errors").textContent = String(response.data.length);
    $("#error-list").innerHTML = response.data.map(renderError).join("") || `<div class="list-row"><span>沒有近期錯誤</span></div>`;
  } catch (error) {
    $("#error-list").innerHTML = `<div class="list-row"><span>讀取錯誤失敗：${escapeHtml(error.message)}</span></div>`;
  }
}

function renderError(error) {
  return `
    <div class="list-row">
      <div>
        <strong>${escapeHtml(error.code || "-")} · ${labelDataset(error.dataset)}</strong>
        <span>${escapeHtml(error.message || "-")}</span>
      </div>
      ${pill(error.severity === "BLOCK" ? "BLOCKED" : "RECHECK")}
    </div>
  `;
}

async function loadEvents() {
  try {
    const response = await api("/api/v1/events?limit=12");
    $("#event-list").innerHTML = response.data.map(renderEvent).join("") || `<div class="list-row"><span>沒有近期事件</span></div>`;
  } catch (error) {
    $("#event-list").innerHTML = `<div class="list-row"><span>讀取事件失敗：${escapeHtml(error.message)}</span></div>`;
  }
}

function renderEvent(event) {
  return `
    <div class="list-row">
      <div>
        <strong>${escapeHtml(event.event_type || "-")} · ${labelDataset(event.dataset)}</strong>
        <span>${escapeHtml(event.period || "-")} ${escapeHtml(event.market || "")} ${escapeHtml(event.stock_id || "")}</span>
      </div>
      <span class="pill">${escapeHtml(event.created_at || "-")}</span>
    </div>
  `;
}

async function loadJobs() {
  try {
    const response = await api("/api/v1/jobs?limit=5");
    const running = response.data.find((job) => !job.terminal);
    $("#metric-job").textContent = running ? running.status : "待命";
    $("#metric-job-detail").textContent = running ? labelDataset(running.dataset) : "single writer guard";
    if (running) {
      renderJob(running);
      pollJob(running.job_id);
    }
  } catch {
    $("#metric-job").textContent = "未啟用";
  }
}

function openUpdateModal(dataset) {
  state.pendingDataset = dataset;
  $("#update-title").textContent = `手動更新${labelDataset(dataset)}`;
  $("#update-message").textContent = `將執行 ${UPDATE_HINTS[dataset]}。`;
  $("#update-modal").hidden = false;
}

function closeUpdateModal() {
  state.pendingDataset = null;
  $("#update-modal").hidden = true;
}

async function startUpdateJob() {
  const dataset = state.pendingDataset;
  if (!dataset) return;
  $("#confirm-update").disabled = true;
  try {
    const response = await api("/api/v1/jobs/update-dataset", {
      method: "POST",
      body: JSON.stringify({ dataset }),
    });
    closeUpdateModal();
    renderJob(response.data);
    pollJob(response.data.job_id);
  } catch (error) {
    alert(`啟動失敗：${error.message}`);
  } finally {
    $("#confirm-update").disabled = false;
  }
}

function pollJob(jobId) {
  clearInterval(state.jobPollTimer);
  state.jobPollTimer = setInterval(async () => {
    try {
      const response = await api(`/api/v1/jobs/${encodeURIComponent(jobId)}`);
      renderJob(response.data);
      if (response.data.terminal) {
        clearInterval(state.jobPollTimer);
        await Promise.allSettled([loadDatasets(), loadBatches(), loadErrors(), loadEvents()]);
      }
    } catch {
      clearInterval(state.jobPollTimer);
    }
  }, 3000);
}

function renderJob(job) {
  $("#job-drawer").hidden = false;
  $("#job-detail").innerHTML = `
    <div class="list-row">
      <div>
        <strong>${labelDataset(job.dataset)} · ${escapeHtml(job.job_id)}</strong>
        <span>${escapeHtml(job.command.join(" "))}</span>
      </div>
      ${pill(job.status)}
    </div>
    <dl class="info-list">
      <dt>建立</dt><dd>${escapeHtml(job.created_at || "-")}</dd>
      <dt>開始</dt><dd>${escapeHtml(job.started_at || "-")}</dd>
      <dt>完成</dt><dd>${escapeHtml(job.finished_at || "-")}</dd>
      <dt>returncode</dt><dd>${job.returncode ?? "-"}</dd>
    </dl>
    ${job.error_message ? `<p class="pill error">${escapeHtml(job.error_message)}</p>` : ""}
    <h2>stdout tail</h2>
    <pre>${escapeHtml(job.stdout_tail || "-")}</pre>
    <h2>stderr tail</h2>
    <pre>${escapeHtml(job.stderr_tail || "-")}</pre>
  `;
}

async function runQuery(event) {
  event.preventDefault();
  const dataset = $("#query-dataset").value;
  const params = new URLSearchParams();
  if ($("#query-from").value) params.set("from", $("#query-from").value);
  if ($("#query-to").value) params.set("to", $("#query-to").value);
  if ($("#query-stock").value.trim()) params.set("stock_id", $("#query-stock").value.trim());
  if ($("#query-market").value) params.set("market", $("#query-market").value);
  params.set("limit", "20");
  try {
    const response = await api(`/api/v1/${dataset}?${params.toString()}`);
    $("#query-result").textContent = JSON.stringify(response.data, null, 2);
  } catch (error) {
    $("#query-result").textContent = `查詢失敗：${error.message}`;
  }
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const token = localStorage.getItem("veristock_api_token");
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const response = await fetch(path, { ...options, headers, cache: "no-store" });
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;
  if (!response.ok || (data && data.ok === false)) {
    throw new Error(data?.error?.message || data?.code || response.statusText);
  }
  return data;
}

function loadToken() {
  $("#api-token").value = localStorage.getItem("veristock_api_token") || "";
}

function labelDataset(dataset) {
  return DATASET_LABELS[dataset] || dataset || "-";
}

function pill(status) {
  const value = String(status || "UNKNOWN");
  const cls = value === "OK" || value === "DONE" ? "ok" : value === "BLOCKED" || value === "FAILED" || value === "ERROR" ? "error" : value === "RECHECK" || value === "MISSING" || value === "RUNNING" ? "warn" : "";
  return `<span class="pill ${cls}">${escapeHtml(value)}</span>`;
}

function rowMessage(message, colspan) {
  return `<tr><td colspan="${colspan}" class="muted">${message}</td></tr>`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
