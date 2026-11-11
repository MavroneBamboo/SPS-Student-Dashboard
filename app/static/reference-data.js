export function createReferenceDataWorkspace({$, api, run, notice, cell, showPanel, role}) {
  const descriptions = {
    categories: "Manage student categories. Existing category values are copied into this catalog by the migration.",
    institutions: "Manage institution names used by student and reporting workflows.",
    "academic-years": "Manage academic-year labels and optional effective dates. Existing student academic years are preserved.",
  };
  const titles = {categories: "category", institutions: "institution", "academic-years": "academic year"};
  let currentCatalog = "categories";
  let retentionPreviewReady = false;
  let retentionPurgeToken = null;

  function clear() {
    $("reference-catalog-rows").replaceChildren();
    $("reference-catalog-create").reset();
    $("reference-catalog-help").textContent = "";
    $("student-import-retention-status").textContent = "Retention status has not been loaded.";
    $("student-import-retention-result").textContent = "";
    $("student-import-retention-confirm").checked = false;
    $("student-import-retention-purge").disabled = true;
    retentionPreviewReady = false;
    retentionPurgeToken = null;
  }

  function field(tag, value, type = "text") {
    const input = document.createElement(tag);
    if (tag === "input") input.type = type;
    input.value = value ?? "";
    return input;
  }

  function editableCell(row, value, tag = "input", type = "text") {
    const td = cell(row, "");
    const input = field(tag, value, type);
    input.disabled = role() !== "IT Administrator" && role() !== "Superuser";
    td.append(input);
    return input;
  }

  function render(rows) {
    const body = $("reference-catalog-rows");
    body.replaceChildren();
    for (const item of rows) {
      const row = document.createElement("tr");
      const name = editableCell(row, item.name);
      const description = editableCell(row, item.description, "textarea");
      const effectiveFrom = editableCell(row, item.effective_from, "input", "date");
      const effectiveTo = editableCell(row, item.effective_to, "input", "date");
      for (const dateField of [effectiveFrom, effectiveTo]) dateField.disabled ||= currentCatalog !== "academic-years";
      cell(row, item.is_active ? "Active" : "Archived");
      cell(row, item.version);
      const actions = cell(row, "");
      if (role() === "IT Administrator" || role() === "Superuser") {
        const save = document.createElement("button");
        save.type = "button";
        save.textContent = "Save";
        save.setAttribute("aria-label", `Save ${item.name}`);
        save.addEventListener("click", () => run(save, async () => {
          const payload = {expected_version: item.version};
          if (name.value.trim() !== item.name) payload.name = name.value.trim();
          if ((description.value || "") !== (item.description || "")) payload.description = description.value.trim() || null;
          if (currentCatalog === "academic-years") {
            if ((effectiveFrom.value || null) !== item.effective_from) payload.effective_from = effectiveFrom.value || null;
            if ((effectiveTo.value || null) !== item.effective_to) payload.effective_to = effectiveTo.value || null;
          }
          if (Object.keys(payload).length === 1) {
            notice("No reference value changes to save.");
            return;
          }
          await api(`/student-reference/catalogs/${currentCatalog}/${item.id}`, "PATCH", payload);
          await refresh();
          notice(`Updated ${name.value.trim()}.`);
        }));
        const toggle = document.createElement("button");
        toggle.type = "button";
        toggle.className = "secondary";
        toggle.textContent = item.is_active ? "Archive" : "Reactivate";
        toggle.setAttribute("aria-label", `${item.is_active ? "Archive" : "Reactivate"} ${item.name}`);
        toggle.addEventListener("click", () => run(toggle, async () => {
          await api(`/student-reference/catalogs/${currentCatalog}/${item.id}`, "PATCH", {
            expected_version: item.version, is_active: !item.is_active,
          });
          await refresh();
          notice(`${item.name} ${item.is_active ? "archived" : "reactivated"}.`);
        }));
        actions.append(save, toggle);
      }
      body.append(row);
    }
    if (!rows.length) {
      const row = document.createElement("tr");
      cell(row, "No reference values are configured for this catalog.").colSpan = 7;
      body.append(row);
    }
  }

  function renderRetention(data, {previewed = false} = {}) {
    const status = $("student-import-retention-status");
    const result = $("student-import-retention-result");
    status.textContent = data.enabled
      ? `Retention: ${data.retention_days} days. ${data.eligible_batches} eligible payload(s): ${data.eligible_preview_batches} preview(s), ${data.eligible_committed_batches} committed batch(es).${data.oldest_eligible_created_at ? ` Oldest: ${new Date(data.oldest_eligible_created_at).toLocaleString()}.` : ""}`
      : "Retention purging is disabled (STUDENT_IMPORT_RETENTION_DAYS is 0). No payloads are eligible.";
    result.textContent = "";
    retentionPreviewReady = previewed && data.enabled && data.eligible_batches > 0 && Boolean(data.purge_token);
    retentionPurgeToken = retentionPreviewReady ? data.purge_token : null;
    $("student-import-retention-confirm").checked = false;
    $("student-import-retention-purge").disabled = !retentionPreviewReady || !$("student-import-retention-confirm").checked;
  }

  async function refreshRetention() {
    const data = await api("/student-imports/retention");
    renderRetention(data);
  }

  async function refresh() {
    const [rows] = await Promise.all([
      api(`/student-reference/catalogs/${currentCatalog}?include_inactive=true`),
      refreshRetention(),
    ]);
    render(rows);
  }

  function selectCatalog(catalog) {
    currentCatalog = catalog;
    for (const button of document.querySelectorAll("[data-reference-tab]")) {
      const selected = button.dataset.referenceTab === catalog;
      button.classList.toggle("is-selected", selected);
      button.setAttribute("aria-selected", String(selected));
    }
    $("reference-catalog-help").textContent = descriptions[catalog];
    $("reference-catalog-form-title").textContent = `Add ${titles[catalog]}`;
    for (const label of document.querySelectorAll("[data-reference-dates]")) label.hidden = catalog !== "academic-years";
    $("reference-catalog-create").reset();
    if (role() === "IT Administrator" || role() === "Superuser") {
      $("reference-catalog-create").hidden = false;
    } else {
      $("reference-catalog-create").hidden = true;
    }
    run($("reference-catalog-create"), refresh);
  }

  async function show() {
    if (role() !== "IT Administrator" && role() !== "Superuser") {
      throw new Error("Reference data administration is not available for this role.");
    }
    showPanel("reference-data");
    selectCatalog(currentCatalog);
  }

  for (const button of document.querySelectorAll("[data-reference-tab]")) {
    button.addEventListener("click", () => selectCatalog(button.dataset.referenceTab));
  }
  $("refresh-reference-data").addEventListener("click", (event) => run(event.currentTarget, refresh));
  $("student-import-retention-dry-run").addEventListener("click", (event) => run(event.currentTarget, async () => {
    const data = await api("/student-imports/retention/purge", "POST", {apply: false});
    renderRetention(data, {previewed: true});
    $("student-import-retention-result").textContent = `Dry run complete: ${data.eligible_batches} encrypted payload(s) would be purged. No data was changed.`;
  }));
  $("student-import-retention-confirm").addEventListener("change", () => {
    $("student-import-retention-purge").disabled = !retentionPreviewReady || !$("student-import-retention-confirm").checked;
  });
  $("student-import-retention-purge").addEventListener("click", (event) => {
    const button = event.currentTarget;
    run(button, async () => {
      if (!retentionPreviewReady || !retentionPurgeToken || !$("student-import-retention-confirm").checked) {
        throw new Error("Preview eligible payloads and confirm the purge first.");
      }
      const data = await api("/student-imports/retention/purge", "POST", {apply: true, purge_token: retentionPurgeToken});
      renderRetention(data);
      $("student-import-retention-result").textContent = `${data.purged_batches} encrypted payload(s) purged. Student profiles, import outcomes and audit records were retained.`;
    }).finally(() => {
      button.disabled = !retentionPreviewReady || !$("student-import-retention-confirm").checked;
    });
  });
  $("reference-catalog-create").addEventListener("submit", (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    run(form, async () => {
      const fields = Object.fromEntries(new FormData(form));
      const payload = {name: fields.name.trim(), description: fields.description.trim() || null};
      if (currentCatalog === "academic-years") {
        payload.effective_from = fields.effective_from || null;
        payload.effective_to = fields.effective_to || null;
      }
      const created = await api(`/student-reference/catalogs/${currentCatalog}`, "POST", payload);
      form.reset();
      await refresh();
      notice(`Added ${created.name} to the ${currentCatalog.replaceAll("-", " ")} catalog.`);
    });
  });

  return {clear, show, refresh};
}
