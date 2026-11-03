export function createStudentCatalogWorkspace({$, api, run, notice}) {
  let categories = [];
  let institutions = [];

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
    const [categoryRows, institutionRows] = await Promise.all([
      api("/student-reference/categories"),
      api("/student-reference/institutions"),
    ]);
    categories = categoryRows;
    institutions = institutionRows;
    renderRows("categories", categories, "student-category-rows");
    renderRows("institutions", institutions, "institution-rows");
    $("student-catalog-status").textContent = `${categories.length} categories and ${institutions.length} institutions loaded.`;
    return {categories, institutions};
  }

  async function refresh() {
    await load();
  }

  function clear() {
    categories = [];
    institutions = [];
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

  $("refresh-student-catalogs").addEventListener("click", () => run($("refresh-student-catalogs"), refresh));
  return {load, refresh, clear};
}
