export function createReferenceDataWorkspace({$, api, run, notice, cell, showPanel, role}) {
  const descriptions = {
    categories: "Manage student categories. Existing category values are copied into this catalog by the migration.",
    institutions: "Manage institution names used by student and reporting workflows.",
    "academic-years": "Manage academic-year labels and optional effective dates. Existing student academic years are preserved.",
  };
  const titles = {categories: "category", institutions: "institution", "academic-years": "academic year"};
  let currentCatalog = "categories";

  function clear() {
    $("reference-catalog-rows").replaceChildren();
    $("reference-catalog-create").reset();
    $("reference-catalog-help").textContent = "";
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

  async function refresh() {
    const rows = await api(`/student-reference/catalogs/${currentCatalog}?include_inactive=true`);
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
