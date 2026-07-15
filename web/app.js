const DATASET_LABELS = {
  daily_close: "Close",
  attention_notice: "注意公告",
  disposal_notice: "處置公告",
  legal_investor: "法人",
  margin: "資券",
  day_trading: "當沖",
  revenue: "月營收",
  security_master: "股票基本資料",
};

const UPDATE_HINTS = {
  daily_close: "update-close",
  attention_notice: "update-attention",
  disposal_notice: "update-disposal",
  legal_investor: "update-legal",
  margin: "update-margin",
  day_trading: "update-day-trading",
  revenue: "update-revenue",
  security_master: "update-security-master",
};

const MONTHLY_QUERY_ROUTES = new Set(["monthly-revenue"]);

const FIELD_LABELS = {
  trade_date: "交易日期",
  revenue_month: "營收月份",
  market: "市場",
  stock_id: "證券代號",
  stock_name: "證券名稱",
  open_cents: "開盤價",
  high_cents: "最高價",
  low_cents: "最低價",
  close_cents: "收盤價",
  volume: "成交股數",
  amount: "成交金額",
  transactions: "成交筆數",
  notice_text: "注意公告",
  disposal_start_date: "處置起日",
  disposal_end_date: "處置迄日",
  reason_text: "處置原因",
  disposal_text: "處置內容",
  foreign_buy: "外陸資買進",
  foreign_sell: "外陸資賣出",
  foreign_net: "外陸資買賣超",
  investment_trust_buy: "投信買進",
  investment_trust_sell: "投信賣出",
  investment_trust_net: "投信買賣超",
  dealer_buy: "自營商買進",
  dealer_sell: "自營商賣出",
  dealer_net: "自營商買賣超",
  dealer_hedge_buy: "自營商避險買進",
  dealer_hedge_sell: "自營商避險賣出",
  dealer_hedge_net: "自營商避險買賣超",
  margin_buy: "融資買進",
  margin_sell: "融資賣出",
  margin_cash_repay: "融資現償",
  previous_margin_balance: "前資餘額",
  margin_balance: "融資餘額",
  margin_limit: "融資限額",
  short_buy: "融券買進",
  short_sell: "融券賣出",
  short_stock_repay: "融券現償",
  previous_short_balance: "前券餘額",
  short_balance: "融券餘額",
  short_limit: "融券限額",
  offsetting: "資券互抵",
  note: "註記",
  suspend_sell_note: "暫停先賣後買註記",
  day_trade_volume: "當沖成交股數",
  day_trade_buy_amount: "當沖買進金額",
  day_trade_sell_amount: "當沖賣出金額",
  industry: "產業別",
  report_date: "申報日期",
  roc_period: "民國年月",
  current_month_revenue: "本月營收",
  previous_month_revenue: "上月營收",
  previous_year_month_revenue: "去年同月營收",
  month_over_month_pct: "月增率(%)",
  year_over_year_pct: "年增率(%)",
  cumulative_revenue: "累計營收",
  previous_year_cumulative_revenue: "去年累計營收",
  cumulative_growth_pct: "累計年增率(%)",
};

const PRICE_CENT_FIELDS = new Set(["open_cents", "high_cents", "low_cents", "close_cents"]);

const pageTitles = {
  dashboard: ["總覽", "本地真理資料庫狀態與排程更新摘要"],
  datasets: ["資料集狀態", "檢查最新資料、問題批次，必要時手動重新更新"],
  batches: ["批次紀錄", "查看 import_batches 狀態與最近更新結果"],
  events: ["錯誤事件", "查看 import_errors 與 data_events"],
  query: ["查詢", "使用 Local Truth API 查詢正式資料"],
  jobs: ["手動更新", "查看手動更新紀錄、錯誤摘要與輸出尾端"],
  system: ["系統", "版本、API 與本機 PWA 設定"],
};

const state = {
  datasets: [],
  statuses: new Map(),
  pendingDataset: null,
  selectedDataset: null,
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
  $("#reload-jobs").addEventListener("click", loadJobs);
  $("#reload-schedule-health").addEventListener("click", loadScheduleHealth);
  $("#reload-dataset-health-check").addEventListener("click", loadDatasetHealthCheck);
  $("#reload-dataset-detail").addEventListener("click", () => {
    if (state.selectedDataset) loadDatasetHealth(state.selectedDataset);
  });
  $("#close-dataset-detail").addEventListener("click", closeDatasetDetail);
  $("#cancel-update").addEventListener("click", closeUpdateModal);
  $("#confirm-update").addEventListener("click", startUpdateJob);
  $("#query-dataset").addEventListener("change", updateQueryDateInputs);
  $("#close-job").addEventListener("click", () => {
    $("#job-drawer").hidden = true;
  });
  $("#save-token").addEventListener("click", () => {
    localStorage.setItem("veristock_api_token", $("#api-token").value.trim());
    refreshAll();
  });
  $("#query-form").addEventListener("submit", runQuery);
  updateQueryDateInputs();
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
  if (active === "datasets") {
    loadDatasets();
    if (state.selectedDataset) loadDatasetHealth(state.selectedDataset);
  }
  else if (active === "batches") loadBatches();
  else if (active === "events") {
    loadErrors();
    loadEvents();
  } else if (active === "system") {
    loadInfo();
    loadScheduleHealth();
    loadDatasetHealthCheck();
  } else refreshAll();
}

async function refreshAll() {
  await Promise.allSettled([
    loadInfo(),
    loadDatasets(),
    loadBatches(),
    loadErrors(),
    loadEvents(),
    loadJobs(),
    loadScheduleHealth(),
    loadDatasetHealthCheck(),
  ]);
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
      <tr class="clickable-row ${state.selectedDataset === dataset.dataset ? "selected-row" : ""}" data-dataset-detail="${escapeHtml(dataset.dataset)}">
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
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      openUpdateModal(button.dataset.update);
    });
  });
  $$("[data-dataset-detail]").forEach((row) => {
    row.addEventListener("click", () => openDatasetDetail(row.dataset.datasetDetail));
  });
}

async function openDatasetDetail(dataset) {
  state.selectedDataset = dataset;
  $("#dataset-detail-panel").hidden = false;
  renderDatasets();
  await loadDatasetHealth(dataset);
}

function closeDatasetDetail() {
  state.selectedDataset = null;
  $("#dataset-detail-panel").hidden = true;
  renderDatasets();
}

async function loadDatasetHealth(dataset) {
  $("#dataset-detail-title").textContent = `${labelDataset(dataset)}健康詳情`;
  $("#dataset-detail-subtitle").textContent = dataset;
  setDatasetDetailLoading("讀取中");
  try {
    const response = await api(`/api/v1/datasets/${encodeURIComponent(dataset)}/health`);
    renderDatasetHealth(response.data);
  } catch (error) {
    $("#dataset-detail-metrics").innerHTML = `<div class="detail-message">讀取失敗：${escapeHtml(error.message)}</div>`;
    clearDatasetDetailLists();
  }
}

function setDatasetDetailLoading(message) {
  $("#dataset-detail-metrics").innerHTML = `<div class="detail-message">${escapeHtml(message)}</div>`;
  clearDatasetDetailLists();
}

function clearDatasetDetailLists() {
  $("#dataset-detail-batches").innerHTML = emptyList("尚無資料");
  $("#dataset-detail-problems").innerHTML = emptyList("尚無資料");
  $("#dataset-detail-errors").innerHTML = emptyList("尚無資料");
  $("#dataset-detail-events").innerHTML = emptyList("尚無資料");
  $("#dataset-detail-jobs").innerHTML = emptyList("尚無資料");
}

function renderDatasetHealth(health) {
  const quality = health.quality || {};
  const summary = health.summary || {};
  $("#dataset-detail-title").textContent = `${labelDataset(health.dataset)}健康詳情`;
  $("#dataset-detail-subtitle").textContent = `${escapeHtml(health.dataset)} · ${escapeHtml(health.period_type || "-")}`;
  $("#dataset-detail-metrics").innerHTML = `
    <article class="mini-metric">
      <span>最新資料</span>
      <strong>${escapeHtml(health.latest_period || "-")}</strong>
    </article>
    <article class="mini-metric">
      <span>品質</span>
      <strong>${pillText(quality.status || "UNKNOWN")}</strong>
    </article>
    <article class="mini-metric">
      <span>問題批次</span>
      <strong>${quality.problem_batches ?? 0}</strong>
    </article>
    <article class="mini-metric">
      <span>OK 批次</span>
      <strong>${summary.OK ?? 0}</strong>
    </article>
    <article class="mini-metric">
      <span>RECHECK</span>
      <strong>${summary.RECHECK ?? 0}</strong>
    </article>
    <article class="mini-metric">
      <span>MISSING</span>
      <strong>${summary.MISSING ?? 0}</strong>
    </article>
  `;
  $("#dataset-detail-batches").innerHTML = renderDetailList(health.recent_batches, renderDetailBatch, "沒有近期批次");
  $("#dataset-detail-problems").innerHTML = renderDetailList(health.problem_batches, renderDetailBatch, "沒有問題批次");
  $("#dataset-detail-errors").innerHTML = renderDetailList(health.recent_errors, renderDetailError, "沒有近期錯誤");
  $("#dataset-detail-events").innerHTML = renderDetailList(health.recent_events, renderDetailEvent, "沒有近期事件");
  $("#dataset-detail-jobs").innerHTML = renderDetailList(health.recent_jobs, renderDetailJob, "沒有手動更新紀錄");
  $$("#dataset-detail-jobs [data-job-id]").forEach((node) => {
    node.addEventListener("click", () => openJobDetail(node.dataset.jobId));
  });
}

function renderDetailList(items, renderer, emptyMessage) {
  return Array.isArray(items) && items.length ? items.map(renderer).join("") : emptyList(emptyMessage);
}

function emptyList(message) {
  return `<div class="list-row"><span>${escapeHtml(message)}</span></div>`;
}

function renderDetailBatch(batch) {
  return `
    <div class="list-row">
      <div>
        <strong>${escapeHtml(batch.period || "-")} · ${escapeHtml(batch.market || "-")}</strong>
        <span>rows ${batch.row_count ?? "-"} · retry ${batch.retry_count ?? 0}</span>
        ${batch.error_summary ? `<span class="error-text">${escapeHtml(batch.error_summary)}</span>` : ""}
      </div>
      ${pill(batch.status)}
    </div>
  `;
}

function renderDetailError(error) {
  return `
    <div class="list-row">
      <div>
        <strong>${escapeHtml(error.code || "-")} · ${escapeHtml(error.severity || "-")}</strong>
        <span>${escapeHtml(error.message || "-")}</span>
        <span>${escapeHtml(error.created_at || "-")}</span>
      </div>
      ${pill(error.severity === "BLOCK" ? "BLOCKED" : "RECHECK")}
    </div>
  `;
}

function renderDetailEvent(event) {
  return `
    <div class="list-row">
      <div>
        <strong>${escapeHtml(event.event_type || "-")} · ${escapeHtml(event.period || "-")}</strong>
        <span>${escapeHtml(event.market || "-")} ${escapeHtml(event.stock_id || "")} ${escapeHtml(event.stock_name || "")}</span>
        ${event.note ? `<span>${escapeHtml(event.note)}</span>` : ""}
      </div>
      <span class="pill">${escapeHtml(event.created_at || "-")}</span>
    </div>
  `;
}

function renderDetailJob(job) {
  return `
    <div class="list-row clickable-row ${job.status === "FAILED" ? "failed-row" : ""}" data-job-id="${escapeHtml(job.job_id)}">
      <div>
        <strong>${escapeHtml(job.status || "-")} · ${escapeHtml(job.job_id || "-")}</strong>
        <span>${escapeHtml(job.finished_at || job.created_at || "-")}</span>
        ${job.error_message ? `<span class="error-text">${escapeHtml(job.error_message)}</span>` : ""}
      </div>
      ${pill(job.status)}
    </div>
  `;
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
    const response = await api("/api/v1/jobs?limit=20");
    const running = response.data.find((job) => !job.terminal);
    const latest = response.data[0];
    $("#metric-job").textContent = running ? running.status : latest ? latest.status : "待命";
    $("#metric-job-detail").textContent = running
      ? labelDataset(running.dataset)
      : latest
        ? `${labelDataset(latest.dataset)} · ${latest.finished_at || latest.created_at || "-"}`
        : "single writer guard";
    renderJobs(response.data);
    if (running) {
      renderJob(running);
      pollJob(running.job_id);
    }
  } catch (error) {
    $("#metric-job").textContent = "未啟用";
    $("#job-table").innerHTML = rowMessage(`讀取手動更新失敗：${escapeHtml(error.message)}`, 6);
    $("#dashboard-jobs").innerHTML = `<div class="list-row"><span>讀取手動更新失敗：${escapeHtml(error.message)}</span></div>`;
  }
}

function renderJobs(jobs) {
  $("#job-table").innerHTML = jobs.map(renderJobRow).join("") || rowMessage("沒有手動更新紀錄", 6);
  $("#dashboard-jobs").innerHTML = jobs.slice(0, 5).map(renderJobCompact).join("") || `<div class="list-row"><span>沒有手動更新紀錄</span></div>`;
  $$("[data-job-id]").forEach((node) => {
    node.addEventListener("click", () => openJobDetail(node.dataset.jobId));
  });
}

function renderJobRow(job) {
  const failedClass = job.status === "FAILED" ? " failed-row" : "";
  return `
    <tr class="clickable-row${failedClass}" data-job-id="${escapeHtml(job.job_id)}">
      <td>
        <strong>${labelDataset(job.dataset)}</strong>
        <div class="subtle">${escapeHtml(job.job_id)}</div>
      </td>
      <td>${pill(job.status)}</td>
      <td>${escapeHtml(job.created_at || "-")}</td>
      <td>${escapeHtml(job.finished_at || "-")}</td>
      <td>${job.returncode ?? "-"}</td>
      <td class="job-error-cell">${escapeHtml(job.error_message || "-")}</td>
    </tr>
  `;
}

function renderJobCompact(job) {
  return `
    <div class="list-row clickable-row ${job.status === "FAILED" ? "failed-row" : ""}" data-job-id="${escapeHtml(job.job_id)}">
      <div>
        <strong>${labelDataset(job.dataset)} · ${escapeHtml(job.status)}</strong>
        <span>${escapeHtml(job.finished_at || job.created_at || "-")}</span>
        ${job.error_message ? `<span class="error-text">${escapeHtml(job.error_message)}</span>` : ""}
      </div>
      ${pill(job.status)}
    </div>
  `;
}

async function openJobDetail(jobId) {
  try {
    const response = await api(`/api/v1/jobs/${encodeURIComponent(jobId)}`);
    renderJob(response.data);
  } catch (error) {
    alert(`讀取 job 失敗：${error.message}`);
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
        await Promise.allSettled([loadDatasets(), loadBatches(), loadErrors(), loadEvents(), loadJobs()]);
      }
    } catch {
      clearInterval(state.jobPollTimer);
    }
  }, 3000);
}

function renderJob(job) {
  $("#job-drawer").hidden = false;
  const messages = Array.isArray(job.messages) ? job.messages : [];
  $("#job-detail").innerHTML = `
    <div class="list-row">
      <div>
        <strong>${labelDataset(job.dataset)} · ${escapeHtml(job.job_id)}</strong>
        <span>${escapeHtml((job.command || []).join(" "))}</span>
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
    <h2>messages</h2>
    <div class="compact-list job-messages">
      ${
        messages.length
          ? messages.map((message) => `
              <div class="list-row">
                <div>
                  <strong>${escapeHtml(message.code || "-")}</strong>
                  <span>${escapeHtml(message.message || "-")}</span>
                </div>
                ${pill(message.level || "INFO")}
              </div>
            `).join("")
          : `<div class="list-row"><span>沒有訊息</span></div>`
      }
    </div>
    <h2>stdout tail</h2>
    <pre>${escapeHtml(job.stdout_tail || "-")}</pre>
    <h2>stderr tail</h2>
    <pre>${escapeHtml(job.stderr_tail || "-")}</pre>
  `;
}

async function loadScheduleHealth() {
  const table = $("#schedule-health-table");
  if (!table) return;
  try {
    const response = await api("/api/v1/ops/schedule-health");
    table.innerHTML = response.data.schedules.map(renderScheduleRow).join("") || rowMessage("沒有排程資料", 9);
  } catch (error) {
    table.innerHTML = rowMessage(`讀取排程健康失敗：${escapeHtml(error.message)}`, 9);
  }
}

async function loadDatasetHealthCheck() {
  const table = $("#dataset-health-check-table");
  if (!table) return;
  try {
    const response = await api("/api/v1/ops/dataset-health-check");
    table.innerHTML = response.data.datasets.map(renderDatasetHealthCheckRow).join("") || rowMessage("沒有資料", 8);
  } catch (error) {
    table.innerHTML = rowMessage(`讀取全資料集健康檢查失敗：${escapeHtml(error.message)}`, 8);
  }
}

function renderDatasetHealthCheckRow(item) {
  const latest = item.latest || {};
  const latestText = Object.entries(latest)
    .map(([market, period]) => `${market}:${period || "-"}`)
    .join(" ");
  const gapSamples = (item.gap?.samples || [])
    .slice(0, 4)
    .map((row) => `${row.market}:${row.period}`)
    .join(", ");
  const message = gapSamples ? `${item.message} · ${gapSamples}` : item.message;
  return `
    <tr>
      <td>
        <strong>${labelDataset(item.dataset)}</strong>
        <div class="subtle">${escapeHtml(item.table || "-")}</div>
      </td>
      <td>${pill(item.status)}</td>
      <td>${item.row_count ?? "-"}</td>
      <td>${item.duplicate_keys ?? "-"}</td>
      <td>${item.gap?.missing_count ?? "-"}</td>
      <td>${item.recent_error_count ?? "-"}</td>
      <td>${escapeHtml(latestText || "-")}</td>
      <td>${escapeHtml(message || "-")}</td>
    </tr>
  `;
}

function renderScheduleRow(item) {
  const data = item.data || {};
  const timer = item.timer || {};
  const log = item.log || {};
  const title = item.title || labelDataset(item.dataset);
  return `
    <tr>
      <td>
        <strong>${escapeHtml(title)}</strong>
        <div class="subtle">${escapeHtml(item.dataset || "-")}</div>
      </td>
      <td>${pill(item.status)}</td>
      <td title="${escapeHtml(timer.message || "")}">${pill(timer.status)}</td>
      <td title="${escapeHtml(log.message || "")}">${pill(log.status)}</td>
      <td title="${escapeHtml(data.message || "")}">${pill(data.status)}</td>
      <td>${escapeHtml(data.observed_period || "-")}</td>
      <td>${escapeHtml(data.expected_period || "-")}</td>
      <td>${escapeHtml(timer.last_trigger || "-")}</td>
      <td>${escapeHtml(timer.next_trigger || "-")}</td>
    </tr>
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
  params.set("limit", normalizedNumber($("#query-limit").value, 10000, 1, 10000));
  params.set("offset", normalizedNumber($("#query-offset").value, 0, 0, Number.MAX_SAFE_INTEGER));
  try {
    const response = await api(`/api/v1/${dataset}?${params.toString()}`);
    renderQueryResult(response);
  } catch (error) {
    $("#query-summary").textContent = `查詢失敗：${error.message}`;
    $("#query-head").innerHTML = "";
    $("#query-result").innerHTML = "";
  }
}

function updateQueryDateInputs() {
  const dataset = $("#query-dataset").value;
  const isMonthly = MONTHLY_QUERY_ROUTES.has(dataset);
  $("#query-from").type = isMonthly ? "month" : "date";
  $("#query-to").type = isMonthly ? "month" : "date";
  $("#query-from").placeholder = isMonthly ? "2026-05" : "2026-06-30";
  $("#query-to").placeholder = isMonthly ? "2026-05" : "2026-06-30";
}

function renderQueryResult(response) {
  const rows = Array.isArray(response.data) ? response.data : [];
  const fields = response.meta?.fields?.length ? response.meta.fields : inferFields(rows);
  const pagination = response.meta?.pagination || {};
  const quality = response.meta?.quality?.status || "UNKNOWN";
  $("#query-summary").innerHTML = `
    <span>${rows.length} 筆</span>
    <span>limit ${pagination.limit ?? "-"}</span>
    <span>offset ${pagination.offset ?? "-"}</span>
    <span>${pagination.has_more ? "還有更多資料" : "已到本頁結尾"}</span>
    ${pill(quality)}
  `;
  if (!rows.length) {
    $("#query-head").innerHTML = "";
    $("#query-result").innerHTML = rowMessage("查無資料", Math.max(fields.length, 1));
    return;
  }
  $("#query-head").innerHTML = `
    <tr>${fields.map((field) => `<th title="${escapeHtml(field)}">${escapeHtml(fieldLabel(field))}</th>`).join("")}</tr>
  `;
  $("#query-result").innerHTML = rows
    .map((row) => `
      <tr>
        ${fields.map((field) => `<td>${escapeHtml(displayCellValue(field, row[field]))}</td>`).join("")}
      </tr>
    `)
    .join("");
}

function inferFields(rows) {
  if (!rows.length || typeof rows[0] !== "object" || rows[0] === null) return [];
  return Object.keys(rows[0]);
}

function fieldLabel(field) {
  return FIELD_LABELS[field] || field;
}

function displayCellValue(field, value) {
  if (value === null || value === undefined) return "";
  if (!PRICE_CENT_FIELDS.has(field)) return value;
  const numberValue = Number(value);
  if (!Number.isFinite(numberValue)) return value;
  return (numberValue / 100).toFixed(2);
}

function normalizedNumber(value, fallback, min, max) {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) return String(fallback);
  return String(Math.min(Math.max(parsed, min), max));
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
  const cls = value === "OK" || value === "DONE" ? "ok" : value === "BLOCKED" || value === "FAILED" || value === "ERROR" ? "error" : value === "WARN" || value === "RECHECK" || value === "MISSING" || value === "RUNNING" ? "warn" : "";
  return `<span class="pill ${cls}">${escapeHtml(value)}</span>`;
}

function pillText(status) {
  return String(status || "UNKNOWN");
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
