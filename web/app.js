/* Finance Workflow Dashboard — front end.
 *
 * No framework and no build step: the API returns render-ready shapes, so the
 * job here is DOM assembly plus a hash router. Every chart ships a table-view
 * twin, so no value is reachable only through colour or a tooltip.
 */

const api = {
  async get(path) {
    const response = await fetch(path, { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`GET ${path} failed: ${response.status}`);
    return response.json();
  },
  async post(path, body) {
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(`POST ${path} failed: ${response.status} ${detail}`);
    }
    return response.json();
  },
};

const state = {
  filters: { search: "", domain_id: "", criticality: "", status: "" },
  reference: null,
  workflows: [],
  chatHistory: [],
  chatBusy: false,
};

// ---------- formatting ----------

const pct = (value, digits = 0) =>
  value === null || value === undefined ? "—" : `${(value * 100).toFixed(digits)}%`;

const hours = (value) => (value === null || value === undefined ? "—" : `${value.toFixed(1)}h`);

const TITLE_CASE = {
  ad_hoc: "Ad hoc",
  under_review: "Under review",
  in_progress: "In progress",
  tax_compliance: "Tax & Compliance",
};
const label = (value) =>
  !value ? "—" : TITLE_CASE[value] ?? value.charAt(0).toUpperCase() + value.slice(1);

const formatDate = (iso) => {
  if (!iso) return "—";
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
};

/** Severity band for an on-time rate. Drives the meter fill and nothing else —
 *  the percentage is always written beside it, so colour never carries it alone. */
const band = (rate) => (rate === null || rate === undefined ? "" : rate >= 0.9 ? "good" : rate >= 0.8 ? "warning" : "critical");

const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

const escapeHtml = (value) =>
  String(value).replace(/[&<>"']/g, (ch) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]),
  );

// ---------- tooltip ----------

const tooltip = document.getElementById("chart-tooltip");

function attachTooltip(node, html) {
  const show = (event) => {
    tooltip.innerHTML = html;
    tooltip.hidden = false;
    const rect = tooltip.getBoundingClientRect();
    const x = Math.min(event.clientX + 14, window.innerWidth - rect.width - 10);
    const y = Math.max(event.clientY - rect.height - 12, 10);
    tooltip.style.left = `${x}px`;
    tooltip.style.top = `${y}px`;
  };
  node.addEventListener("mouseenter", show);
  node.addEventListener("mousemove", show);
  node.addEventListener("mouseleave", () => {
    tooltip.hidden = true;
  });
  // Keyboard parity: focusing a mark shows the same content as hovering it.
  node.addEventListener("focus", () => {
    const box = node.getBoundingClientRect();
    show({ clientX: box.left + box.width / 2, clientY: box.top });
  });
  node.addEventListener("blur", () => {
    tooltip.hidden = true;
  });
}

// ---------- KPI row ----------

function renderKpis(metrics) {
  const row = document.getElementById("kpi-row");
  row.replaceChildren();

  const tiles = [
    {
      label: "Processes in scope",
      value: String(metrics.total_workflows),
      note: `${metrics.active_workflows} active · ${metrics.draft_workflows} draft · ${metrics.total_steps} steps`,
      hero: true,
    },
    {
      label: "On time",
      value: pct(metrics.on_time_rate),
      note: `across ${metrics.total_runs} recorded runs`,
    },
    {
      label: "Unattended steps",
      value: pct(metrics.automation_rate),
      note: "automated or system, no person in the loop",
    },
    {
      label: "Open exceptions",
      value: String(metrics.open_exceptions),
      note: `${metrics.high_severity_open_exceptions} high severity`,
    },
    {
      label: "At risk",
      value: String(metrics.at_risk_workflows),
      note: "high or critical, under 80% on time",
    },
  ];

  for (const tile of tiles) {
    const card = el("div", "kpi");
    card.append(
      el("span", "kpi__label", tile.label),
      el("span", `kpi__value${tile.hero ? " kpi__value--hero" : ""}`, tile.value),
      el("span", "kpi__note", tile.note),
    );
    row.append(card);
  }
}

// ---------- domain chart ----------

function renderDomainChart(metrics) {
  const host = document.getElementById("domain-chart");
  host.replaceChildren();

  const rows = metrics.by_domain.filter((d) => d.on_time_rate !== null);
  if (!rows.length) {
    host.append(el("p", "empty", "No completed runs to chart yet."));
    return;
  }

  const bars = el("div", "bars");
  for (const row of rows) {
    // Nominal categories, single series → one colour for every bar. A darker
    // step for bigger values would double-encode the length as hue.
    const line = el("div", "bar-row");
    line.tabIndex = 0;
    line.append(el("span", "bar-row__label", row.domain_name));

    const track = el("div", "bar-row__track");
    const fill = el("div", "bar-row__fill");
    fill.style.width = `${Math.max(row.on_time_rate * 100, 1)}%`;
    track.append(fill);

    line.append(track, el("span", "bar-row__value", pct(row.on_time_rate)));
    attachTooltip(
      line,
      `<strong>${escapeHtml(row.domain_name)}</strong><br>${pct(row.on_time_rate)} on time<br>` +
        `${row.workflow_count} processes · ${row.step_count} steps<br>` +
        `${row.open_exceptions} open exception(s)`,
    );
    bars.append(line);
  }

  const axis = el("div", "axis");
  const scale = el("div", "axis__scale");
  scale.append(el("span", null, "0%"), el("span", null, "50%"), el("span", null, "100%"));
  axis.append(scale);

  host.append(bars, axis);

  // Table twin.
  const table = document.getElementById("domain-table");
  table.replaceChildren(
    buildTable(
      ["Domain", "Processes", "Steps", "On time", "Open exceptions"],
      rows.map((row) => [
        row.domain_name,
        { value: row.workflow_count, num: true },
        { value: row.step_count, num: true },
        { value: pct(row.on_time_rate), num: true },
        { value: row.open_exceptions, num: true },
      ]),
    ),
  );
}

function buildTable(headers, rows) {
  const table = el("table", "data");
  const thead = el("thead");
  const headRow = el("tr");
  headers.forEach((header, index) => {
    const th = el("th", index > 0 ? "num" : null, header);
    headRow.append(th);
  });
  thead.append(headRow);

  const tbody = el("tbody");
  for (const cells of rows) {
    const tr = el("tr");
    for (const cell of cells) {
      const isObject = cell !== null && typeof cell === "object";
      const td = el("td", isObject && cell.num ? "num" : null, String(isObject ? cell.value : cell));
      tr.append(td);
    }
    tbody.append(tr);
  }
  table.append(thead, tbody);
  return table;
}

// ---------- workflow list ----------

function renderWorkflowList(workflows) {
  const host = document.getElementById("workflow-list");
  const count = document.getElementById("workflow-count");
  host.replaceChildren();

  count.textContent = workflows.length
    ? `${workflows.length} process${workflows.length === 1 ? "" : "es"}, most critical and least reliable first`
    : "No processes match the current filters";

  if (!workflows.length) {
    host.append(el("p", "empty", "Nothing matches those filters. Try clearing the search."));
    return;
  }

  const list = el("div", "wf-list");
  for (const workflow of workflows) {
    const row = el("button", "wf-row");
    row.type = "button";
    row.addEventListener("click", () => {
      window.location.hash = `#/workflow/${workflow.id}`;
    });

    const name = el("div");
    name.append(el("div", "wf-row__name", workflow.name));
    name.append(
      el(
        "div",
        "wf-row__meta",
        `${workflow.domain_name} · ${label(workflow.frequency)} · ${workflow.step_count} steps · SLA ${workflow.sla_hours}h`,
      ),
    );

    const owner = el("div", "wf-row__owner", workflow.owner_name);

    const meter = el("div", "wf-row__meter");
    meter.append(buildMeter(workflow.metrics.on_time_rate));

    const criticality = el("div");
    const pill = el("span", `pill pill--${workflow.criticality}`);
    pill.append(el("span", "pill__dot"), document.createTextNode(label(workflow.criticality)));
    criticality.append(pill);

    const runs = el("div", "wf-row__runs");
    runs.append(
      el(
        "span",
        "tag",
        workflow.metrics.total_runs ? `${workflow.metrics.total_runs} runs` : label(workflow.status),
      ),
    );

    row.append(name, owner, meter, criticality, runs);
    list.append(row);
  }
  host.append(list);
}

function buildMeter(rate) {
  const meter = el("div", "meter");
  const track = el("div", "meter__track");
  const fill = el("div", `meter__fill meter__fill--${band(rate) || "good"}`);
  fill.style.width = rate === null || rate === undefined ? "0%" : `${rate * 100}%`;
  track.append(fill);
  meter.append(track, el("span", "meter__value", pct(rate)));
  meter.title = rate === null ? "No finished runs yet" : `${pct(rate)} of finished runs met SLA`;
  return meter;
}

// ---------- detail view ----------

const STEP_TYPES = [
  ["automated", "Automated"],
  ["manual", "Manual"],
  ["system", "System"],
  ["approval", "Approval"],
  ["review", "Review"],
];

async function renderDetail(workflowId) {
  const host = document.getElementById("view-detail");
  host.replaceChildren(el("p", "empty", "Loading process…"));

  let detail;
  try {
    detail = await api.get(`/api/workflows/${encodeURIComponent(workflowId)}`);
  } catch (error) {
    host.replaceChildren(el("p", "empty", `Could not load that process. ${error.message}`));
    return;
  }

  const { workflow, domain, owner, systems, data_objects: objects, metrics, recent_runs: runs } = detail;
  const systemName = Object.fromEntries(systems.map((s) => [s.id, s.name]));
  const objectName = Object.fromEntries(objects.map((o) => [o.id, o.name]));

  const root = el("div", "detail");

  // Head
  const back = el("button", "back-link", "← All processes");
  back.type = "button";
  back.addEventListener("click", () => {
    window.location.hash = "#/";
  });

  const head = el("div", "detail__head");
  head.append(el("h2", "detail__title", workflow.name), el("p", "detail__desc", workflow.description));

  const pills = el("div", "detail__pills");
  const crit = el("span", `pill pill--${workflow.criticality}`);
  crit.append(el("span", "pill__dot"), document.createTextNode(`${label(workflow.criticality)} criticality`));
  pills.append(
    crit,
    el("span", "tag", domain.name),
    el("span", "tag", label(workflow.status)),
    el("span", "tag", `${label(workflow.maturity)} maturity`),
    ...workflow.tags.map((tag) => el("span", "tag", tag)),
  );
  head.append(pills);

  const headCard = el("section", "card");
  headCard.append(back, head);
  root.append(headCard);

  // Facts + metrics
  const factsCard = el("section", "card");
  const facts = el("div", "meta-grid");
  const factItems = [
    ["Owner", `${owner.name}`, owner.role],
    ["Cadence", label(workflow.frequency), `SLA ${workflow.sla_hours}h`],
    ["Steps", String(workflow.step_count), `${workflow.planned_hours}h planned effort`],
    ["On time", pct(metrics.on_time_rate), `${metrics.total_runs} runs recorded`],
    ["Average duration", hours(metrics.avg_duration_hours), `against a ${workflow.sla_hours}h SLA`],
    ["Unattended steps", pct(metrics.automation_rate), `${metrics.failed_runs} failed runs`],
    ["Open exceptions", String(metrics.open_exceptions), `last run ${formatDate(metrics.last_run_at)}`],
  ];
  for (const [name, value, note] of factItems) {
    const item = el("div", "meta-grid__item");
    item.append(
      el("span", "meta-grid__label", name),
      el("span", "meta-grid__value", value),
      el("span", "kpi__note", note),
    );
    facts.append(item);
  }
  factsCard.append(facts);
  if (workflow.risk_notes) {
    const note = el("p", "card__sub");
    note.style.marginTop = "14px";
    note.append(el("strong", null, "Known risk: "), document.createTextNode(workflow.risk_notes));
    factsCard.append(note);
  }
  root.append(factsCard);

  // Process flow
  const flowCard = el("section", "card");
  const flowHead = el("div", "card__head");
  const flowTitle = el("div");
  flowTitle.append(
    el("h2", null, "Process flow"),
    el(
      "p",
      "card__sub",
      "Each step in sequence, with the systems it touches and the business objects it consumes and produces. Those objects are the starting point for the ontology.",
    ),
  );
  flowHead.append(flowTitle);
  flowCard.append(flowHead);

  const flow = el("div", "flow");
  for (const step of workflow.steps) {
    const node = el("div", "flow-step");
    node.append(el("div", "flow-step__seq", String(step.seq)));
    node.append(el("div", `flow-step__rail type-${step.type}`));

    const body = el("div", "flow-step__body");
    body.append(el("div", "flow-step__name", step.name));
    body.append(el("div", "flow-step__desc", step.description));

    const factsLine = el("div", "flow-step__facts");
    // The step type is written out, not left to the rail colour alone.
    factsLine.append(
      el("span", null, label(step.type)),
      el("span", null, step.role),
      el("span", null, `${step.duration_minutes} min`),
    );
    if (step.system_ids.length) {
      factsLine.append(el("span", null, step.system_ids.map((id) => systemName[id] ?? id).join(", ")));
    }
    body.append(factsLine);

    if (step.input_object_ids.length || step.output_object_ids.length) {
      const io = el("div", "flow-step__io");
      for (const id of step.input_object_ids) io.append(el("span", "io-chip", `in: ${objectName[id] ?? id}`));
      for (const id of step.output_object_ids) io.append(el("span", "io-chip io-chip--out", `out: ${objectName[id] ?? id}`));
      body.append(io);
    }

    if (step.controls.length) {
      const controls = el("div", "flow-step__facts");
      for (const control of step.controls) {
        controls.append(el("span", null, `⛉ ${control.name} (${control.type}, ${control.framework})`));
      }
      body.append(controls);
    }

    node.append(body);
    flow.append(node);
  }
  flowCard.append(flow);

  const legend = el("div", "legend");
  for (const [type, name] of STEP_TYPES) {
    const item = el("div", "legend__item");
    item.append(el("span", `legend__swatch type-${type}`), document.createTextNode(name));
    legend.append(item);
  }
  flowCard.append(legend);
  root.append(flowCard);

  // Systems, objects, controls
  const cols = el("div", "two-col");
  cols.append(
    buildListCard("Systems", systems.map((s) => [s.name, s.kind])),
    buildListCard(
      "Business objects",
      objects.map((o) => [o.name, o.description]),
      "Candidate entities for the ontology.",
    ),
  );
  const controls = workflow.steps.flatMap((step) =>
    step.controls.map((control) => [control.name, `${label(control.type)} · ${control.framework} · ${step.name}`]),
  );
  if (controls.length) cols.append(buildListCard("Controls", controls));
  root.append(cols);

  // Run history
  root.append(buildRunHistory(runs, workflow.sla_hours));

  // Open exceptions
  let openExceptions = [];
  try {
    openExceptions = await api.get(`/api/exceptions?workflow_id=${encodeURIComponent(workflowId)}&limit=25`);
  } catch {
    openExceptions = [];
  }
  const excCard = el("section", "card");
  const excHead = el("div", "card__head");
  const excTitle = el("div");
  excTitle.append(
    el("h2", null, "Open exceptions"),
    el("p", "card__sub", "Unresolved issues raised during recorded runs, highest severity first."),
  );
  excHead.append(excTitle);
  excCard.append(excHead);

  if (!openExceptions.length) {
    excCard.append(el("p", "empty", "No open exceptions on this process."));
  } else {
    for (const exception of openExceptions) {
      const item = el("div", "exception");
      item.append(el("span", `exception__sev exception__sev--${exception.severity}`, exception.severity));
      const body = el("div", "exception__body");
      body.append(document.createTextNode(exception.description));
      body.append(
        el(
          "div",
          "exception__where",
          `${exception.step_name ?? exception.step_id} · ${exception.period} · run ${exception.run_id}`,
        ),
      );
      item.append(body);
      excCard.append(item);
    }
  }
  root.append(excCard);

  host.replaceChildren(root);
  // Land at the top of the process rather than under the sticky header.
  window.scrollTo({ top: 0 });
}

function buildListCard(title, entries, subtitle) {
  const card = el("section", "card");
  const head = el("div", "card__head");
  const titleWrap = el("div");
  titleWrap.append(el("h2", null, title));
  if (subtitle) titleWrap.append(el("p", "card__sub", subtitle));
  head.append(titleWrap);
  card.append(head);

  const list = el("ul", "list-plain");
  for (const [name, note] of entries) {
    const item = el("li");
    item.append(el("strong", null, name));
    if (note) item.append(document.createTextNode(` — ${note}`));
    list.append(item);
  }
  card.append(list);
  return card;
}

function buildRunHistory(runs, slaHours) {
  const card = el("section", "card");
  const head = el("div", "card__head");
  const titleWrap = el("div");
  titleWrap.append(
    el("h2", null, "Run history"),
    el("p", "card__sub", "Duration of each recorded run against the SLA. Newest on the right."),
  );
  head.append(titleWrap);

  const toggleGroup = el("div", "toggle-group");
  toggleGroup.setAttribute("role", "group");
  toggleGroup.setAttribute("aria-label", "Chart or table view");
  const chartBtn = el("button", "toggle", "Chart");
  const tableBtn = el("button", "toggle", "Table");
  chartBtn.type = tableBtn.type = "button";
  chartBtn.setAttribute("aria-pressed", "true");
  tableBtn.setAttribute("aria-pressed", "false");
  toggleGroup.append(chartBtn, tableBtn);
  head.append(toggleGroup);
  card.append(head);

  const ordered = [...runs].reverse(); // oldest → newest, left to right
  const chartHost = el("div", "runchart");
  const tableHost = el("div");
  tableHost.hidden = true;

  if (!ordered.length) {
    chartHost.append(el("p", "empty", "This process has no recorded runs yet."));
  } else {
    const durations = ordered.map((run) => run.duration_hours ?? 0);
    const ceiling = Math.max(...durations, slaHours) * 1.15;

    const plot = el("div", "runchart__plot");
    for (const run of ordered) {
      const value = run.duration_hours ?? 0;
      const column = el("div", "runchart__col");
      const outcome =
        run.status === "in_progress" ? "progress" : run.sla_met ? "met" : "breach";
      column.classList.add(`runchart__col--${outcome}`);
      column.style.height = `${Math.max((value / ceiling) * 100, run.status === "in_progress" ? 6 : 2)}%`;
      column.tabIndex = 0;
      attachTooltip(
        column,
        `<strong>${escapeHtml(run.period)}</strong><br>` +
          `${run.status === "in_progress" ? "Still running" : `${value.toFixed(1)}h against a ${slaHours}h SLA`}<br>` +
          `${label(run.status)}${run.status === "in_progress" ? "" : run.sla_met ? " · within SLA" : " · SLA breached"}<br>` +
          `started ${formatDate(run.started_at)}`,
      );
      plot.append(column);
    }

    const slaRule = el("div", "runchart__sla");
    slaRule.style.bottom = `${(slaHours / ceiling) * 100}%`;
    slaRule.append(el("span", null, `SLA ${slaHours}h`));
    plot.append(slaRule);
    chartHost.append(plot);

    const foot = el("div", "runchart__foot");
    foot.append(
      el("span", null, ordered[0].period),
      el("span", null, ordered[ordered.length - 1].period),
    );
    chartHost.append(foot);

    const legend = el("div", "legend");
    for (const [cls, name] of [
      ["met", "Within SLA"],
      ["breach", "SLA breached"],
      ["progress", "In progress"],
    ]) {
      const item = el("div", "legend__item");
      item.append(el("span", `legend__swatch runchart__col--${cls}`), document.createTextNode(name));
      legend.append(item);
    }
    chartHost.append(legend);

    tableHost.append(
      buildTable(
        ["Period", "Started", "Status", "Duration", "SLA met"],
        ordered
          .slice()
          .reverse()
          .map((run) => [
            run.period,
            { value: formatDate(run.started_at), num: true },
            { value: label(run.status), num: true },
            { value: run.duration_hours === null ? "—" : hours(run.duration_hours), num: true },
            { value: run.sla_met === null ? "—" : run.sla_met ? "Yes" : "No", num: true },
          ]),
      ),
    );
  }

  card.append(chartHost, tableHost);
  wireToggle(chartBtn, tableBtn, chartHost, tableHost);
  return card;
}

function wireToggle(chartBtn, tableBtn, chartHost, tableHost) {
  const select = (showChart) => {
    chartHost.hidden = !showChart;
    tableHost.hidden = showChart;
    chartBtn.setAttribute("aria-pressed", String(showChart));
    tableBtn.setAttribute("aria-pressed", String(!showChart));
  };
  chartBtn.addEventListener("click", () => select(true));
  tableBtn.addEventListener("click", () => select(false));
}

// ---------- chat ----------

/** Minimal Markdown for model output: escape first, then allow bold, inline
 *  code, bullet lists and paragraphs. Nothing that can inject markup. */
function renderMarkdown(text) {
  const inline = (value) =>
    escapeHtml(value)
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, "<code>$1</code>");

  const blocks = [];
  let list = null;

  for (const rawLine of String(text).split("\n")) {
    const line = rawLine.trimEnd();
    const bullet = line.match(/^\s*[-*]\s+(.*)$/);
    if (bullet) {
      list ??= [];
      list.push(`<li>${inline(bullet[1])}</li>`);
      continue;
    }
    if (list) {
      blocks.push(`<ul>${list.join("")}</ul>`);
      list = null;
    }
    if (line.trim()) blocks.push(`<p>${inline(line)}</p>`);
  }
  if (list) blocks.push(`<ul>${list.join("")}</ul>`);
  return blocks.join("");
}

function appendMessage({ role, content, notice, toolCalls, pending }) {
  const log = document.getElementById("chat-log");
  const message = el("div", `msg msg--${role}`);
  message.append(el("span", "msg__role", role === "user" ? "You" : "Assistant"));

  const body = el("div", "msg__body");
  if (pending) {
    const dots = el("span", "thinking");
    dots.append(el("span"), el("span"), el("span"));
    body.append(dots);
  } else if (role === "user") {
    body.textContent = content;
  } else {
    body.innerHTML = renderMarkdown(content);
  }
  message.append(body);

  if (notice) message.append(el("div", "msg__notice", notice));

  if (toolCalls?.length) {
    const sources = el("details", "msg__sources");
    sources.append(el("summary", null, `Sources — ${toolCalls.length} data quer${toolCalls.length === 1 ? "y" : "ies"}`));
    const list = el("div");
    for (const call of toolCalls) {
      const args = Object.entries(call.arguments ?? {})
        .map(([key, value]) => `${key}=${JSON.stringify(value)}`)
        .join(", ");
      list.append(el("div", null, `${call.name}(${args})`));
    }
    sources.append(list);
    message.append(sources);
  }

  log.append(message);
  log.scrollTop = log.scrollHeight;
  return message;
}

async function sendChat(question) {
  if (state.chatBusy || !question.trim()) return;
  state.chatBusy = true;
  const sendButton = document.getElementById("chat-send");
  sendButton.disabled = true;

  appendMessage({ role: "user", content: question });
  const placeholder = appendMessage({ role: "assistant", pending: true });

  try {
    const response = await api.post("/api/chat", {
      message: question,
      history: state.chatHistory.slice(-10),
    });
    placeholder.remove();
    appendMessage({
      role: "assistant",
      content: response.reply,
      notice: response.notice,
      toolCalls: response.tool_calls,
    });
    state.chatHistory.push({ role: "user", content: question });
    state.chatHistory.push({ role: "assistant", content: response.reply });
  } catch (error) {
    placeholder.remove();
    appendMessage({
      role: "assistant",
      content: "That request failed before it reached the assistant.",
      notice: error.message,
    });
  } finally {
    state.chatBusy = false;
    sendButton.disabled = false;
  }
}

const SUGGESTIONS = [
  "Which processes are most at risk?",
  "What is going wrong in the close?",
  "Where is manual effort concentrated?",
  "Which business objects show up most often?",
];

function renderSuggestions() {
  const host = document.getElementById("chat-suggestions");
  host.replaceChildren();
  for (const text of SUGGESTIONS) {
    const chip = el("button", "suggestion", text);
    chip.type = "button";
    chip.addEventListener("click", () => sendChat(text));
    host.append(chip);
  }
}

// ---------- filters & routing ----------

let searchTimer = null;

async function refreshWorkflows() {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(state.filters)) {
    if (value) params.set(key, value);
  }
  const query = params.toString();
  state.workflows = await api.get(`/api/workflows${query ? `?${query}` : ""}`);
  renderWorkflowList(state.workflows);
}

function wireFilters() {
  const search = document.getElementById("filter-search");
  search.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.filters.search = search.value.trim();
      refreshWorkflows();
    }, 220);
  });

  const selects = [
    ["filter-domain", "domain_id"],
    ["filter-criticality", "criticality"],
    ["filter-status", "status"],
  ];
  for (const [id, key] of selects) {
    document.getElementById(id).addEventListener("change", (event) => {
      state.filters[key] = event.target.value;
      refreshWorkflows();
    });
  }

  document.getElementById("filter-reset").addEventListener("click", () => {
    state.filters = { search: "", domain_id: "", criticality: "", status: "" };
    search.value = "";
    for (const [id] of selects) document.getElementById(id).value = "";
    refreshWorkflows();
  });
}

function wireDomainToggle() {
  const chart = document.getElementById("domain-chart");
  const table = document.getElementById("domain-table");
  const [chartBtn, tableBtn] = document.querySelectorAll('[data-view-target="domain"]');
  wireToggle(chartBtn, tableBtn, chart, table);
}

function route() {
  const match = window.location.hash.match(/^#\/workflow\/(.+)$/);
  const listView = document.getElementById("view-list");
  const detailView = document.getElementById("view-detail");
  const filters = document.querySelector(".filters");

  if (match) {
    listView.hidden = true;
    filters.hidden = true;
    detailView.hidden = false;
    renderDetail(decodeURIComponent(match[1]));
  } else {
    detailView.hidden = true;
    detailView.replaceChildren();
    filters.hidden = false;
    listView.hidden = false;
  }
}

// ---------- theme & chrome ----------

function wireTheme() {
  const stored = localStorage.getItem("fwd-theme");
  if (stored) document.documentElement.dataset.theme = stored;

  document.getElementById("theme-toggle").addEventListener("click", () => {
    const isDark =
      document.documentElement.dataset.theme === "dark" ||
      (!document.documentElement.dataset.theme &&
        window.matchMedia("(prefers-color-scheme: dark)").matches);
    const next = isDark ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("fwd-theme", next);
  });
}

function wireChatPanel() {
  const layout = document.getElementById("layout");
  const toggle = document.getElementById("chat-toggle");
  toggle.addEventListener("click", () => {
    const hidden = layout.dataset.chat === "hidden";
    layout.dataset.chat = hidden ? "shown" : "hidden";
    toggle.setAttribute("aria-expanded", String(hidden));
  });

  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const question = input.value;
    input.value = "";
    input.style.height = "auto";
    sendChat(question);
  });

  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 140)}px`;
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
}

// ---------- boot ----------

async function boot() {
  wireTheme();
  wireFilters();
  wireDomainToggle();
  wireChatPanel();
  renderSuggestions();
  window.addEventListener("hashchange", route);

  try {
    const [health, metrics, reference] = await Promise.all([
      api.get("/api/health"),
      api.get("/api/metrics"),
      api.get("/api/reference"),
    ]);

    state.reference = reference;

    document.getElementById("header-sub").textContent =
      `${metrics.total_workflows} finance processes · ${metrics.total_steps} steps · data as at ${formatDate(health.as_of)}`;

    const badge = document.getElementById("chat-mode-badge");
    badge.hidden = false;
    if (health.chat.mode === "azure_ai_foundry") {
      badge.textContent = `Azure AI Foundry · ${health.chat.deployment}`;
      badge.classList.add("badge--live");
      document.getElementById("chat-sub").textContent =
        "Grounded in the dashboard data via Azure AI Foundry. Every answer lists the queries behind it.";
    } else {
      badge.textContent = "Assistant offline";
      document.getElementById("chat-sub").textContent =
        "Azure AI Foundry is not configured, so replies come from the built-in keyword responder over the same data.";
    }

    const domainSelect = document.getElementById("filter-domain");
    for (const domain of reference.domains) {
      const option = el("option", null, domain.name);
      option.value = domain.id;
      domainSelect.append(option);
    }

    renderKpis(metrics);
    renderDomainChart(metrics);
    await refreshWorkflows();
    route();
  } catch (error) {
    document.getElementById("header-sub").textContent = `Could not load the portfolio: ${error.message}`;
  }
}

boot();
