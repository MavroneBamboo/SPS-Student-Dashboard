export function createStudentCatalogWorkspace({$, api, run, notice}) {
  let categories = [];
  let institutions = [];
  let academicYears = [];

  function renderAcademicYears() {
    const body = $("academic-year-rows");
    body.replaceChildren();
    for (const item of academicYears) {
      const row = document.createElement("tr");
      const code = document.createElement("td");
      code.textContent = item.code;
      row.append(code);
      const labelCell = document.createElement("td");
      const label = document.createElement("input");
      label.value = item.label;
      label.maxLength = 80;
      label.setAttribute("aria-label", `${item.code} label`);
      labelCell.append(label);
      row.append(labelCell);
      const startCell = document.createElement("td");
      const starts = document.createElement("input");
      starts.type = "date";
      starts.value = item.starts_on ?? "";
      starts.setAttribute("aria-label", `${item.code} starts on`);
      startCell.append(starts);
      row.append(startCell);
      const endCell = document.createElement("td");
      const ends = document.createElement("input");
      ends.type = "date";
      ends.value = item.ends_on ?? "";
      ends.setAttribute("aria-label", `${item.code} ends on`);
      endCell.append(ends);
      row.append(endCell);
      const activeCell = document.createElement("td");
      const active = document.createElement("input");
      active.type = "checkbox";
      active.checked = item.is_active;
      active.setAttribute("aria-label", `${item.code} active`);
      activeCell.append(active);
      row.append(activeCell);
      const version = document.createElement("td");
      version.textContent = String(item.version);
      row.append(version);
      const actionCell = document.createElement("td");
      const save = document.createElement("button");
      save.type = "button";
      save.textContent = "Save";
      save.setAttribute("aria-label", `Save academic year ${item.code}`);
      save.addEventListener("click", () => run(save, async () => {
        const payload = {expected_version: item.version};
        if (label.value.trim() !== item.label) payload.label = label.value.trim();
        if (starts.value !== (item.starts_on ?? "") || ends.value !== (item.ends_on ?? "")) {
          payload.starts_on = starts.value || null;
          payload.ends_on = ends.value || null;
        }
        if (active.checked !== item.is_active) payload.is_active = active.checked;
        if (active.checked && (!starts.value || !ends.value)) throw new Error("Enter both dates before activating this academic year.");
        if (starts.value && ends.value && ends.value < starts.value) throw new Error("The end date must be on or after the start date.");
        if (Object.keys(payload).length === 1) {
          notice(`${item.code} has no changes to save.`);
          return;
        }
        await api(`/student-reference/academic-years/${item.id}`, "PATCH", payload);
        await refresh();
        notice(`Saved academic year ${item.code}.`);
      }));
      actionCell.append(save);
      row.append(actionCell);
      body.append(row);
    }
  }

  function renderRows(kind, items, bodyId) {
    const body = $(bodyId);
    body.replaceChildren();
    for (const item of items) {
      const row = document.createElement("tr");
      const code = document.createElement("td");
      code.textContent = item.code;
      row.append(code);

      const nameCell = document.createElement("td");
      const name = document.createElement("input");
      name.value = item.name;
      name.maxLength = kind === "categories" ? 80 : 120;
      name.setAttribute("aria-label", `${item.code} name`);
      nameCell.append(name);
      row.append(nameCell);

      const activeCell = document.createElement("td");
      const active = document.createElement("input");
      active.type = "checkbox";
      active.checked = item.is_active;
      active.setAttribute("aria-label", `${item.code} active`);
      activeCell.append(active);
      row.append(activeCell);

      const version = document.createElement("td");
      version.textContent = String(item.version);
      row.append(version);

      const actions = document.createElement("td");
      const save = document.createElement("button");
      save.type = "button";
      save.textContent = "Save";
      save.setAttribute("aria-label", `Save ${item.code}`);
      save.addEventListener("click", () => run(save, async () => {
        const payload = {expected_version: item.version};
        if (name.value.trim() !== item.name) payload.name = name.value.trim();
        if (active.checked !== item.is_active) payload.is_active = active.checked;
        if (Object.keys(payload).length === 1) {
          notice(`${item.code} has no changes to save.`);
          return;
        }
        await api(`/student-reference/${kind}/${item.id}`, "PATCH", payload);
        await refresh();
        notice(`Saved ${item.code}.`);
      }));
      actions.append(save);
      row.append(actions);
      body.append(row);
    }
  }

  async function load() {
    const [categoryRows, institutionRows, yearRows] = await Promise.all([
      api("/student-reference/categories"),
      api("/student-reference/institutions"),
      api("/student-reference/academic-years"),
    ]);
    categories = categoryRows;
    institutions = institutionRows;
    academicYears = yearRows;
    renderAcademicYears();
    renderRows("categories", categories, "student-category-rows");
    renderRows("institutions", institutions, "institution-rows");
    $("student-catalog-status").textContent = `${academicYears.length} academic years, ${categories.length} categories and ${institutions.length} institutions loaded.`;
    return {academicYears, categories, institutions};
  }

  async function refresh() {
    await load();
  }

  function clear() {
    categories = [];
    institutions = [];
    academicYears = [];
    $("academic-year-rows").replaceChildren();
    $("student-category-rows").replaceChildren();
    $("institution-rows").replaceChildren();
    $("student-catalog-status").textContent = "";
  }

  for (const [formId, kind, nameLimit] of [
    ["create-category-form", "categories", 80],
    ["create-institution-form", "institutions", 120],
  ]) {
    $(formId).addEventListener("submit", (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      run(form, async () => {
        const payload = Object.fromEntries(new FormData(form));
        payload.code = payload.code.trim();
        payload.name = payload.name.trim();
        if (payload.name.length > nameLimit) throw new Error(`Name must be ${nameLimit} characters or fewer.`);
        await api(`/student-reference/${kind}`, "POST", payload);
        form.reset();
        await refresh();
        notice(`Added ${payload.code}.`);
      });
    });
  }

  $("create-academic-year-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    run(form, async () => {
      const payload = Object.fromEntries(new FormData(form));
      payload.code = payload.code.trim();
      payload.label = payload.label.trim();
      payload.is_active = form.elements.is_active.checked;
      if (!payload.is_active) payload.is_active = false;
      await api("/student-reference/academic-years", "POST", payload);
      form.reset();
      form.elements.is_active.checked = true;
      await refresh();
      notice(`Added academic year ${payload.code}.`);
    });
  });

  $("refresh-student-catalogs").addEventListener("click", () => run($("refresh-student-catalogs"), refresh));
  return {load, refresh, clear};
}
