export function createStudentWorkspace({$, api, run, notice, cell, showPanel}) {
  let selected = null;
  let offset = 0;
  let listRequest = 0;
  let detailRequest = 0;
  let hasMore = false;
  let importBatch = null;
  let categories = [];
  let institutions = [];
  const pageSize = 25;
  const form = $("profile-form");
  const profileFields = [
    "name", "class_name", "class_effective_date", "category", "institution_id", "status", "status_effective", "date_of_birth", "edr_ros", "ic_number",
    "admission_type", "exam_level", "academic_year", "age_in_academic_year", "gender", "language_1", "language_2",
    "math_1", "math_2", "cpa", "science", "humanities", "commerce_1", "commerce_2", "commerce_3", "aa",
    "nationality", "citizenship", "birthplace", "religion", "race", "marital_status", "next_of_kin_name",
    "next_of_kin_nric", "next_of_kin_relationship", "next_of_kin_contact", "next_of_kin_address_ports",
    "next_of_kin_address_from_student", "student_contact",
  ];
  const optionalTextFields = profileFields.filter((key) => !["name", "class_name", "class_effective_date", "category", "institution_id", "status", "status_effective", "date_of_birth", "age_in_academic_year"].includes(key));
  const today = () => {
    const now = new Date();
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  };
  function close() {
    detailRequest += 1;
    selected = null;
    form.reset();
    $("profile-editor").hidden = true;
    $("profile-history").replaceChildren();
    $("profile-class-history").replaceChildren();
    $("profile-version").textContent = "";
  }
  function clear() {
    close();
    categories = [];
    institutions = [];
    $("new-student").disabled = true;
    offset = 0;
    listRequest += 1;
    $("profile-rows").replaceChildren();
    $("profile-page").textContent = "";
    importBatch = null;
    $("student-import-form").reset();
    $("student-import-preview").hidden = true;
    $("student-import-summary").textContent = "";
    $("student-import-errors").replaceChildren();
    $("student-import-warnings").replaceChildren();
    $("student-import-warning-panel").hidden = true;
    $("student-import-warnings-confirm").checked = false;
  }
  async function list() {
    const request = ++listRequest;
    const fields = Object.fromEntries(new FormData($("profile-search")));
    const query = new URLSearchParams(Object.entries(fields).filter(([, value]) => value.trim()));
    query.set("offset", String(offset));
    query.set("limit", String(pageSize + 1));
    const profiles = await api(`/students?${query}`);
    if (request !== listRequest) return;
    $("profile-rows").replaceChildren();
    for (const profile of profiles.slice(0, pageSize)) {
      const row = document.createElement("tr");
      for (const value of [profile.pris_no, profile.name, profile.class_name, profile.category, profile.institution_name ?? "—", profile.status]) cell(row, value);
      const open = document.createElement("button");
      open.textContent = "Open";
      open.setAttribute("aria-label", `Open ${profile.pris_no}`);
      open.addEventListener("click", () => run(open, () => load(profile.id)));
      cell(row, "").append(open);
      $("profile-rows").append(row);
    }
    if (!profiles.length) {
      const row = document.createElement("tr");
      cell(row, "No student profiles match the search.").colSpan = 7;
      $("profile-rows").append(row);
    }
    $("profile-page").textContent = profiles.length ? `Showing ${offset + 1}–${offset + Math.min(profiles.length, pageSize)} profiles` : "No results";
    hasMore = profiles.length > pageSize;
    pager();
  }
  function pager() {
    $("profiles-previous").disabled = offset === 0;
    $("profiles-next").disabled = !hasMore;
  }
  function render(profile) {
    form.reset();
    selected = profile;
    const categorySelect = form.elements.category;
    categorySelect.replaceChildren(new Option("Select a category", ""));
    const activeCategories = categories.filter((item) => item.is_active);
    if (profile?.category_id && !activeCategories.some((item) => item.id === profile.category_id)) {
      const historical = categories.find((item) => item.id === profile.category_id);
      if (historical) categorySelect.add(new Option(`${historical.code} · ${historical.name} (inactive)`, historical.code));
    }
    for (const item of activeCategories) categorySelect.add(new Option(`${item.code} · ${item.name}`, item.code));
    const institutionSelect = form.elements.institution_id;
    institutionSelect.replaceChildren(new Option("No institution selected", ""));
    const activeInstitutions = institutions.filter((item) => item.is_active);
    if (profile?.institution_id && !activeInstitutions.some((item) => item.id === profile.institution_id)) {
      const historical = institutions.find((item) => item.id === profile.institution_id);
      if (historical) institutionSelect.add(new Option(`${historical.code} · ${historical.name} (inactive)`, String(historical.id)));
    }
    for (const item of activeInstitutions) institutionSelect.add(new Option(`${item.code} · ${item.name}`, String(item.id)));
    $("profile-editor").hidden = false;
    $("profile-editor-title").textContent = profile ? "Edit student profile" : "New student profile";
    $("profile-version").textContent = profile ? `Saved version ${profile.version}. Reload if another operator has changed this record.` : "Create a new student using a unique Pris No.";
    $("reload-profile").hidden = !profile;
    for (const key of ["pris_no", ...profileFields]) {
      form.elements[key].value = profile ? profile[key] ?? (key === "class_effective_date" ? today() : "") : key === "status" ? "ACTIVE" : ["status_effective", "class_effective_date"].includes(key) ? today() : "";
    }
    form.elements.pris_no.readOnly = Boolean(profile);
    form.elements.status_effective.disabled = Boolean(profile);
    form.elements.status_effective.required = !profile;
    $("profile-history").replaceChildren();
    $("profile-class-history").replaceChildren();
    form.elements.name.focus();
  }
  async function load(id) {
    const request = ++detailRequest;
    const profile = await api(`/students/${id}`);
    const [history, classHistory] = await Promise.all([
      api(`/students/${id}/status-history`),
      api(`/students/${id}/class-history`),
    ]);
    if (request !== detailRequest) return;
    render(profile);
    for (const entry of history) {
      const row = document.createElement("tr");
      for (const value of [entry.effective_date, entry.previous_status ?? "Initial record", entry.new_status, entry.changed_by]) cell(row, value);
      $("profile-history").append(row);
    }
    for (const entry of classHistory) {
      const row = document.createElement("tr");
      for (const value of [entry.effective_date, entry.class_name, entry.source === "BASELINE" ? "Rollout baseline; earlier class unknown" : entry.source, entry.changed_by ?? "—"]) cell(row, value);
      $("profile-class-history").append(row);
    }
  }
  async function show() {
    showPanel("profiles");
    const newStudentButton = $("new-student");
    newStudentButton.disabled = true;
    try {
      [categories, institutions] = await Promise.all([
        api("/student-reference/categories"),
        api("/student-reference/institutions"),
      ]);
      await list();
    } finally {
      newStudentButton.disabled = !categories.some((item) => item.is_active);
    }
  }
  function importIssueText(item) {
    const messages = {
      duplicate_in_workbook: "duplicate Pris No. within the workbook",
      excel_error_value: "Excel contains an error value",
      formula_not_allowed: "formula is not supported in this field",
      formula_value_missing: "formula has no saved result",
      identifier_must_be_text: "Pris No. must be stored as text",
      invalid_date: "use a valid date",
      invalid_integer: "must be a whole number",
      invalid_value: "value is invalid",
      numeric_cell_may_lose_leading_zeros: "numeric Excel cell; leading zeroes or long digits may be lost",
      numeric_identifier_must_be_integer: "must be a whole number",
      numeric_identifier_must_be_nonnegative: "must be zero or greater",
      out_of_range: "must be from 0 to 120",
      required: "required",
      required_for_new_profile: "required for a new profile",
    };
    return `Workbook row ${item.row_number}, ${item.field}: ${messages[item.code] ?? "check this value"}`;
  }
  function renderImport(batch) {
    importBatch = batch;
    $("student-import-preview").hidden = false;
    $("student-import-summary").textContent = `Batch ${batch.id}: ${batch.row_count} rows; ${batch.valid_count} valid; ${batch.invalid_count} invalid; ${batch.warning_count} data warnings; ${batch.existing_count} match existing profiles; ${batch.new_count} new identifiers. Status: ${batch.status}.`;
    const errors = $("student-import-errors");
    errors.replaceChildren();
    for (const item of batch.row_errors) {
      const line = document.createElement("li");
      line.textContent = importIssueText(item);
      errors.append(line);
    }
    const warningPanel = $("student-import-warning-panel");
    warningPanel.hidden = batch.warning_count === 0;
    const warnings = $("student-import-warnings");
    warnings.replaceChildren();
    for (const item of batch.row_warnings) {
      const line = document.createElement("li");
      line.textContent = importIssueText(item);
      warnings.append(line);
    }
    $("student-import-warnings-confirm").checked = false;
    updateImportButtons();
  }
  function updateImportButtons() {
    const confirmed = !importBatch || importBatch.warning_count === 0 || $("student-import-warnings-confirm").checked;
    $("student-import-create").disabled = !importBatch || importBatch.status !== "PREVIEW" || importBatch.invalid_count > 0 || importBatch.existing_count > 0 || !confirmed;
    $("student-import-update").disabled = !importBatch || importBatch.status !== "PREVIEW" || importBatch.invalid_count > 0 || importBatch.existing_count === 0 || !confirmed;
  }
  $("student-import-form").addEventListener("submit", (event) => {
    event.preventDefault();
    run(event.currentTarget, async () => {
      const file = event.currentTarget.elements.workbook.files[0];
      if (!file) throw new Error("Choose an .xlsx workbook first.");
      if (!file.name.toLowerCase().endsWith(".xlsx")) throw new Error("Only .xlsx workbooks are supported.");
      if (file.size > 10 * 1024 * 1024) throw new Error("The workbook exceeds the 10 MiB upload limit.");
      importBatch = null;
      $("student-import-preview").hidden = true;
      $("student-import-warnings-confirm").checked = false;
      renderImport(await api("/student-imports", "POST", file));
    });
  });
  async function commitImport(button, mode) {
    if (!importBatch) return;
    await run(button, async () => {
      const committed = await api(`/student-imports/${importBatch.id}/commit`, "POST", {
        mode,
        confirm_data_warnings: $("student-import-warnings-confirm").checked,
      });
      renderImport(committed);
      await list();
      notice(`Import ${committed.status.toLowerCase()}: ${committed.result?.created ?? 0} created, ${committed.result?.updated ?? 0} updated, ${committed.result?.unchanged ?? 0} unchanged.`);
    });
    updateImportButtons();
  }
  $("student-import-warnings-confirm").addEventListener("change", updateImportButtons);
  $("student-import-create").addEventListener("click", (event) => commitImport(event.currentTarget, "CREATE_ONLY"));
  $("student-import-update").addEventListener("click", (event) => commitImport(event.currentTarget, "UPDATE_EXISTING"));
  $("new-student").addEventListener("click", () => { detailRequest += 1; render(null); notice(); });
  $("cancel-profile").addEventListener("click", close);
  $("reload-profile").addEventListener("click", () => run($("reload-profile"), () => load(selected.id)));
  form.elements.status.addEventListener("input", () => {
    const changed = !selected || form.elements.status.value.trim().toUpperCase() !== selected.status;
    form.elements.status_effective.disabled = !changed;
    form.elements.status_effective.required = changed;
    form.elements.status_effective.value = changed ? today() : selected?.status_effective ?? "";
  });
  $("profile-search").addEventListener("submit", (event) => {
    event.preventDefault();
    offset = 0;
    run(event.currentTarget, list);
  });
  async function movePage(button, direction) {
    await run(button, async () => {
      const previous = offset;
      offset = Math.max(0, offset + direction * pageSize);
      try { await list(); } catch (error) { offset = previous; throw error; }
    });
    pager();
  }
  $("profiles-previous").addEventListener("click", () => movePage($("profiles-previous"), -1));
  $("profiles-next").addEventListener("click", () => movePage($("profiles-next"), 1));
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    run(form, async () => {
      const request = detailRequest;
      const fields = Object.fromEntries(new FormData(form));
      for (const key of Object.keys(fields)) fields[key] = fields[key].trim();
      fields.status = fields.status.toUpperCase();
      for (const key of [...optionalTextFields, "date_of_birth"]) fields[key] = fields[key] || null;
      fields.age_in_academic_year = fields.age_in_academic_year === "" ? null : Number(fields.age_in_academic_year);
      fields.institution_id = fields.institution_id === "" ? null : Number(fields.institution_id);
      let payload = fields;
      if (selected) {
        payload = {expected_version: selected.version};
        for (const key of profileFields) {
          if (key in fields && fields[key] !== (selected[key] ?? null)) payload[key] = fields[key];
        }
        if (fields.class_name === selected.class_name) delete payload.class_effective_date;
        if (Object.keys(payload).length === 1) { notice("No profile changes to save."); return; }
      }
      const saved = await api(selected ? `/students/${selected.id}` : "/students", selected ? "PATCH" : "POST", payload);
      if (request !== detailRequest) return;
      await load(saved.id);
      await list();
      notice(`Saved student ${saved.pris_no}.`);
    });
  });
  return {clear, show};
}
