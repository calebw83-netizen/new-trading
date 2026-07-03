let currentProposal = null;
let strategyProposal = null;

const statusLine = document.querySelector("#statusLine");
const statusPills = document.querySelector("#statusPills");
const accountsOutput = document.querySelector("#accountsOutput");
const strategyOutput = document.querySelector("#strategyOutput");
const proposalOutput = document.querySelector("#proposalOutput");
const orderOutput = document.querySelector("#orderOutput");
const auditOutput = document.querySelector("#auditOutput");
const previewButton = document.querySelector("#previewOrder");
const executeButton = document.querySelector("#executeOrder");
const loadStrategyProposalButton = document.querySelector("#loadStrategyProposal");
const autoScanButton = document.querySelector("#autoScan");
const autoExecuteButton = document.querySelector("#autoExecute");
const confirmationInput = document.querySelector("#confirmation");
const proposalForm = document.querySelector("#proposalForm");
const strategyForm = document.querySelector("#strategyForm");
const sideSelect = proposalForm.querySelector("[name='side']");
const baseSizeField = document.querySelector("#baseSizeField");

function pretty(value) {
  return JSON.stringify(value, null, 2);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.detail || body.message || "Request failed.");
  }
  return body;
}

function setOrderButtons(enabled) {
  previewButton.disabled = !enabled;
  executeButton.disabled = !enabled;
}

function compactPayload(form) {
  const payload = Object.fromEntries(new FormData(form));
  form.querySelectorAll("input[type='checkbox']").forEach((checkbox) => {
    payload[checkbox.name] = checkbox.checked;
  });
  Object.keys(payload).forEach((key) => {
    if (payload[key] === "") delete payload[key];
  });
  return payload;
}

function renderStrategy(result) {
  const data = result.data;
  const metrics = data.metrics || {};
  const checks = data.checks || [];
  const news = data.news || {};
  const items = news.items || [];
  const newsLines = items.slice(0, 5).map((item) => `- ${item.source}: ${item.title}`);
  const errors = news.errors || [];
  strategyOutput.className =
    data.decision === "BUY" || data.decision === "SELL"
      ? "decision approved"
      : data.score >= 55
        ? "decision watch"
        : "decision blocked";
  strategyOutput.textContent = [
    `${data.decision} | ${data.confidence} | ${data.score}/100`,
    data.rationale,
    "",
    `Buy score ${data.buy_score ?? "-"} | Sell score ${data.sell_score ?? "-"}`,
    `Price ${metrics.last_price || "-"} | RSI ${metrics.rsi14 || "-"} | ATR ${metrics.atr_percent || "-"}% | Volume ${metrics.volume_ratio || "-"}x`,
    `EMA 9/21/50 ${metrics.ema9 || "-"}/${metrics.ema21 || "-"}/${metrics.ema50 || "-"}`,
    `News ${news.auto_fetched ? "auto-fetched" : "manual"} | Bias ${news.news_bias || "-"} | Event risk ${news.event_risk || "-"}`,
    newsLines.length ? "" : "",
    ...newsLines,
    errors.length ? "" : "",
    ...errors.map((error) => `Feed issue: ${error}`),
    "",
    ...checks,
  ].join("\n");
}

function renderScan(scanResult) {
  const scan = scanResult.data;
  renderStrategy({ data: scan.best });
  const bestOverall = scan.best_overall || scan.best;
  const sameBest = bestOverall.product_id === scan.best.product_id;
  const ranked = scan.ranked || [];
  const rankedLines = ranked
    .slice(0, 5)
    .map(
      (item) =>
        `- ${item.product_id}: ${item.decision} ${item.score}/100 ` +
        `(B ${item.buy_score ?? "-"} / S ${item.sell_score ?? "-"})`,
    );
  strategyOutput.textContent = [
    `Auto scan checked ${scan.result_count} Robinhood chart(s) across crypto and stocks.`,
    `Allowed for proposal: ${(scan.allowed_products || []).join(", ")}`,
    sameBest ? "" : `Best overall was ${bestOverall.product_id}, but proposal selection stayed inside guardrails.`,
    "",
    strategyOutput.textContent,
    "",
    "Top scan results:",
    ...rankedLines,
    ...(scan.errors || []).map((error) => `Scan issue: ${error}`),
  ]
    .filter((line) => line !== "")
    .join("\n");
}

async function loadStatus() {
  try {
    const result = await api("/api/status");
    const data = result.data;
    statusLine.textContent = `Mode: ${result.mode}. Credentials: ${
      data.has_credentials ? "configured" : "not configured"
    }.`;
    statusPills.innerHTML = "";
    [
      `Products: ${data.allowed_products.join(", ")}`,
      `Max order: $${data.max_order_quote_usd}`,
      `Daily cap: $${data.daily_quote_limit_usd}`,
      "Charts: Robinhood candles",
      `Assets: ${(data.scan_asset_classes || []).join(", ")}`,
      `News feeds: ${(data.news_feeds || []).length}`,
      `Auto execute: ${data.auto_execute_enabled ? `${data.auto_execute_min_score}+` : "locked"}`,
      `Autopilot: ${data.autopilot?.enabled ? `every ${Math.round(data.autopilot.interval_seconds / 60)}m` : "off"}`,
      data.live_trading_enabled ? "Live execution enabled" : "Live execution locked",
    ].forEach((text) => {
      const pill = document.createElement("span");
      pill.className = `pill ${data.live_trading_enabled ? "live" : ""}`;
      pill.textContent = text;
      statusPills.appendChild(pill);
    });
  } catch (error) {
    statusLine.textContent = error.message;
  }
}

async function loadAccounts() {
  accountsOutput.textContent = "Loading account data...";
  try {
    const result = await api("/api/accounts");
    accountsOutput.textContent = pretty(result.data);
  } catch (error) {
    accountsOutput.textContent = error.message;
  }
}

async function loadAudit() {
  try {
    const result = await api("/api/audit");
    const events = result.data || [];
    auditOutput.innerHTML = "";
    if (!events.length) {
      auditOutput.textContent = "No audit events yet.";
      return;
    }
    events.forEach((event) => {
      const item = document.createElement("div");
      item.className = "audit-item";
      item.innerHTML = `
        <strong>${event.event_type}</strong>
        <span>${event.created_at}</span>
        <span>${event.product_id || ""} ${event.side || ""} ${event.quote_size || ""}</span>
        <span>${event.client_order_id || ""}</span>
      `;
      auditOutput.appendChild(item);
    });
  } catch (error) {
    auditOutput.textContent = error.message;
  }
}

async function loadProposalFromStrategy(proposal) {
  setOrderButtons(false);
  currentProposal = null;
  proposalOutput.className = "decision";
  proposalOutput.textContent = "Running automatic proposal through guardrails...";
  const payload = { ...proposal };
  if (payload.base_size === null) delete payload.base_size;
  const result = await api("/api/proposals", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  currentProposal = result.data;
  proposalOutput.className = `decision ${currentProposal.status}`;
  proposalOutput.textContent = [
    `${currentProposal.status.toUpperCase()} ${currentProposal.side} ${currentProposal.product_id}`,
    `Client order ID: ${currentProposal.client_order_id}`,
    "",
    ...currentProposal.checks,
  ].join("\n");
  setOrderButtons(currentProposal.status === "approved");
  confirmationInput.placeholder = `CONFIRM ${currentProposal.client_order_id}`;
  await loadAudit();
}

function updateSizeFields() {
  baseSizeField.style.display = sideSelect.value === "SELL" ? "grid" : "none";
}

sideSelect.addEventListener("change", updateSizeFields);
updateSizeFields();

strategyForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  strategyProposal = null;
  loadStrategyProposalButton.disabled = true;
  strategyOutput.className = "decision";
  strategyOutput.textContent = "Analyzing chart, sentiment, and news-cycle risk...";
  try {
    const result = await api("/api/strategy/analyze", {
      method: "POST",
      body: JSON.stringify(compactPayload(strategyForm)),
    });
    renderStrategy(result);
    strategyProposal = result.data.proposal;
    loadStrategyProposalButton.disabled = !strategyProposal;
    await loadAudit();
  } catch (error) {
    strategyOutput.className = "decision blocked";
    strategyOutput.textContent = error.message;
  }
});

autoScanButton.addEventListener("click", async () => {
  strategyProposal = null;
  loadStrategyProposalButton.disabled = true;
  setOrderButtons(false);
  strategyOutput.className = "decision";
  strategyOutput.textContent = "Scanning Robinhood crypto and stock charts, plus internet news...";
  proposalOutput.className = "decision";
  proposalOutput.textContent = "Waiting for automatic scan result.";
  try {
    const formPayload = compactPayload(strategyForm);
    const result = await api("/api/strategy/scan", {
      method: "POST",
      body: JSON.stringify({
        bankroll_usd: formPayload.bankroll_usd || "10",
        days_remaining: formPayload.days_remaining || 90,
        base_inventory: formPayload.base_inventory,
      }),
    });
    renderScan(result);
    strategyProposal = result.data.best.proposal;
    loadStrategyProposalButton.disabled = !strategyProposal;
    if (strategyProposal) {
      await loadProposalFromStrategy(strategyProposal);
    } else {
      proposalOutput.className = "decision blocked";
      proposalOutput.textContent = "Auto scan found no trade that cleared the veteran setup filters.";
      await loadAudit();
    }
  } catch (error) {
    strategyOutput.className = "decision blocked";
    strategyOutput.textContent = error.message;
  }
});

autoExecuteButton.addEventListener("click", async () => {
  strategyProposal = null;
  loadStrategyProposalButton.disabled = true;
  setOrderButtons(false);
  strategyOutput.className = "decision";
  strategyOutput.textContent = "Scanning for an 80+ setup before automatic execution...";
  proposalOutput.className = "decision";
  proposalOutput.textContent = "Auto execution will only continue if scan, threshold, and guardrails pass.";
  orderOutput.textContent = "Waiting for auto-execute result...";
  try {
    const formPayload = compactPayload(strategyForm);
    const result = await api("/api/strategy/auto-execute", {
      method: "POST",
      body: JSON.stringify({
        bankroll_usd: formPayload.bankroll_usd || "10",
        days_remaining: formPayload.days_remaining || 90,
        base_inventory: formPayload.base_inventory,
      }),
    });
    renderScan({ data: result.data.scan });
    currentProposal = result.data.proposal;
    proposalOutput.className = "decision approved";
    proposalOutput.textContent = [
      `AUTO EXECUTED ${currentProposal.side} ${currentProposal.product_id}`,
      `Client order ID: ${currentProposal.client_order_id}`,
      `Threshold: ${result.data.threshold}/100`,
      "",
      ...currentProposal.checks,
    ].join("\n");
    orderOutput.textContent = pretty({
      preview: result.data.preview,
      execution: result.data.execution,
    });
    await loadAudit();
  } catch (error) {
    strategyOutput.className = "decision blocked";
    strategyOutput.textContent = error.message;
    orderOutput.textContent = error.message;
  }
});

loadStrategyProposalButton.addEventListener("click", async () => {
  if (!strategyProposal) return;
  try {
    await loadProposalFromStrategy(strategyProposal);
  } catch (error) {
    proposalOutput.className = "decision blocked";
    proposalOutput.textContent = error.message;
  }
});

proposalForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setOrderButtons(false);
  currentProposal = null;
  const payload = compactPayload(event.currentTarget);
  proposalOutput.className = "decision";
  proposalOutput.textContent = "Checking guardrails...";
  try {
    const result = await api("/api/proposals", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    currentProposal = result.data;
    proposalOutput.className = `decision ${currentProposal.status}`;
    proposalOutput.textContent = [
      `${currentProposal.status.toUpperCase()} ${currentProposal.side} ${currentProposal.product_id}`,
      `Client order ID: ${currentProposal.client_order_id}`,
      "",
      ...currentProposal.checks,
    ].join("\n");
    setOrderButtons(currentProposal.status === "approved");
    confirmationInput.placeholder = `CONFIRM ${currentProposal.client_order_id}`;
    await loadAudit();
  } catch (error) {
    proposalOutput.className = "decision blocked";
    proposalOutput.textContent = error.message;
  }
});

previewButton.addEventListener("click", async () => {
  if (!currentProposal) return;
  orderOutput.textContent = "Previewing order...";
  try {
    const result = await api("/api/orders/preview", {
      method: "POST",
      body: JSON.stringify({ proposal: currentProposal }),
    });
    orderOutput.textContent = pretty(result.data);
    await loadAudit();
  } catch (error) {
    orderOutput.textContent = error.message;
  }
});

executeButton.addEventListener("click", async () => {
  if (!currentProposal) return;
  orderOutput.textContent = "Submitting order...";
  try {
    const result = await api("/api/orders/execute", {
      method: "POST",
      body: JSON.stringify({
        proposal: currentProposal,
        confirmation: confirmationInput.value,
      }),
    });
    orderOutput.textContent = pretty(result.data);
    await loadAudit();
  } catch (error) {
    orderOutput.textContent = error.message;
  }
});

document.querySelector("#refreshAccounts").addEventListener("click", loadAccounts);
document.querySelector("#refreshAudit").addEventListener("click", loadAudit);

loadStatus();
loadAccounts();
loadAudit();

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/static/sw.js?v=1").catch(() => {});
}
