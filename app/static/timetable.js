const weekdays = ["MON", "TUE", "WED", "THU", "FRI"];
const periods = ["P1", "P2", "LUNCH", "P3", "P4"];
const periodLabels = {P1: "P1 · Period 1", P2: "P2 · Period 2", LUNCH: "P3 · Lunch / Muster", P3: "P4 · Period 3", P4: "P5 · Period 4"};

export function createTimetableWorkspace({$, api, run, notice, cell, showPanel, role, downloadXlsx}) {
  let versions = [];
  let classes = [];
  let current = null;
  let teachers = [];
  let academicYears = [];
  let draftMutationPending = false;
  let viewBy = "class";
  let pageOffset = 0;
  let detailSequence = 0;
  const currentRole = () => typeof role === "function" ? role() : role;
  const canEdit = () => ["Superuser", "Operator", "IT Administrator"].includes(currentRole());
  const canApprove = () => ["Superuser", "IT Administrator"].includes(currentRole());
  const placementForm = $("timetable-placement-form");

  function clear() {
    versions = [];
    classes = [];
    current = null;
    detailSequence += 1;
    pageOffset = 0;
    for (const id of ["timetable-version-rows", "timetable-grid", "timetable-pending"]) $(id).replaceChildren();
    $("timetable-editor").hidden = true;
    $("timetable-create-form").hidden = true;
    $("new-timetable").hidden = true;
    placementForm.reset();
    placementForm.hidden = true;
    $("timetable-generation-summary").textContent = "";
    viewBy = "class";
    for (const page of document.querySelectorAll(".timetable-page")) page.hidden = page.id !== "timetable-board-page";
    for (const link of document.querySelectorAll(".timetable-side-link")) link.classList.toggle("is-active", link.dataset.timetablePage === "board");
    $("timetable-by-class").classList.add("is-selected");
    $("timetable-by-teacher").classList.remove("is-selected");
    $("timetable-class-filter-wrap").hidden = false;
    $("timetable-teacher-filter-wrap").hidden = true;
    for (const id of ["teacher-availability", "timetable-teacher-rows", "timetable-subject-rows", "timetable-class-rows", "timetable-period-rows", "student-class-mapping-rows", "attendance-class-mapping-rows"]) {
      const element = $(id);
      if (element) element.replaceChildren();
    }
  }

  function editableDraft() {
    return canEdit() && current?.status === "DRAFT";
  }

  function syncDraftMutationControls() {
    const editable = editableDraft();
    const approve = $("timetable-approve");
    $("timetable-generate").disabled = draftMutationPending || !editable;
    approve.disabled = draftMutationPending || !canApprove() || current?.status !== "DRAFT";
    for (const id of ["timetable-remove", "timetable-lock"]) $(id).disabled = draftMutationPending || !editable;
    for (const button of placementForm.querySelectorAll("button")) button.disabled = draftMutationPending || !editable;
    for (const button of $("timetable-grid").querySelectorAll("button")) button.disabled = draftMutationPending || !editable;
  }

  async function runDraftMutation(control, action) {
    if (draftMutationPending) return;
    draftMutationPending = true;
    syncDraftMutationControls();
    try {
      await run(control, action);
    } finally {
      draftMutationPending = false;
      syncDraftMutationControls();
    }
  }

  function renderVersions() {
    const rows = $("timetable-version-rows");
    rows.replaceChildren();
    for (const version of versions) {
      const row = document.createElement("tr");
      const status = version.is_published ? `${version.status} · PUBLISHED` : version.status;
      for (const value of [version.name, version.academic_year, version.week_start, status, `r${version.revision}`]) cell(row, value);
      const open = document.createElement("button");
      open.textContent = "Open";
      open.setAttribute("aria-label", `Open timetable ${version.name}`);
      open.addEventListener("click", () => run(open, () => load(version.id)));
      cell(row, "").append(open);
      rows.append(row);
    }
    if (!versions.length) {
      const row = document.createElement("tr");
      cell(row, "No saved timetables are available.").colSpan = 6;
      rows.append(row);
    }
  }

  async function refresh() {
    const data = await Promise.all([
      api("/timetable/versions?limit=100"),
      api("/timetable/classes"),
      api("/timetable/teachers"),
      api("/student-reference/academic-years"),
    ]);
    versions = data[0];
    classes = data[1].filter((row) => row.is_active);
    teachers = data[2].filter((row) => row.is_active);
    academicYears = data[3].filter((row) => row.is_active && row.starts_on && row.ends_on);
    renderVersions();
    $("student-class-mapping-section").hidden = !["Operator", "IT Administrator", "Superuser"].includes(currentRole());
    const createForm = $("timetable-create-form");
    $("new-timetable").hidden = !canEdit();
    const select = createForm.elements.class_ids;
    select.replaceChildren();
    for (const item of classes) {
      const option = document.createElement("option");
      option.value = item.id;
      option.textContent = `${item.code} · ${item.name}`;
      select.append(option);
    }
    for (const select of [createForm.elements.academic_year, $("timetable-lesson-form").elements.academic_year, $("timetable-rule-form").elements.academic_year]) {
      const previous = select.value;
      select.replaceChildren(new Option("Select academic year", ""));
      for (const year of academicYears) select.add(new Option(`${year.label} · ${year.code}`, year.code));
      if (academicYears.some((year) => year.code === previous)) select.value = previous;
    }
    $("timetable-lesson-form").hidden = !canEdit();
    fillSelect($("timetable-class-filter"), classes, (row) => `${row.code} · ${row.name}`);
    fillSelect($("timetable-teacher-filter"), teachers, (row) => `${row.short_code} · ${row.full_name}`);
    await refreshSetup();
  }

  function fillSelect(select, rows, label) {
    const previous = select.value;
    select.replaceChildren();
    for (const row of rows) {
      const option = document.createElement("option");
      option.value = row.id;
      option.textContent = label(row);
      select.append(option);
    }
    if (rows.some((row) => String(row.id) === previous)) select.value = previous;
  }

  function renderAvailability() {
    const fieldset = $("teacher-availability");
    if (fieldset.childElementCount) return;
    for (const day of weekdays) {
      const row = document.createElement("div");
      row.className = "availability-row";
      const title = document.createElement("strong");
      title.textContent = day;
      row.append(title);
      for (const period of periods.filter((item) => item !== "LUNCH")) {
        const label = document.createElement("label");
        const input = document.createElement("input");
        input.type = "checkbox";
        input.checked = true;
        input.value = period;
        input.dataset.day = day;
        input.setAttribute("aria-label", `${day} ${period}`);
        label.append(input, document.createTextNode(periodLabels[period]));
        row.append(label);
      }
      fieldset.append(row);
    }
  }

  async function refreshSetup() {
    const canConfigure = ["IT Administrator", "Superuser"].includes(currentRole());
    const [teacherRows, subjects, instructionalClasses, clusters, periodRows, classMappings, attendanceMappings] = await Promise.all([
      api("/timetable/teachers"), api("/timetable/subjects"), api("/timetable/classes"), api("/timetable/clusters"), api("/timetable/periods"),
      ["Operator", "IT Administrator", "Superuser"].includes(currentRole()) ? api("/student-reference/class-mappings") : Promise.resolve([]),
      ["Operator", "IT Administrator", "Superuser"].includes(currentRole()) ? api("/student-reference/attendance-class-mappings") : Promise.resolve([]),
    ]);
    const activeTeachers = teacherRows.filter((row) => row.is_active);
    const activeSubjects = subjects.filter((row) => row.is_active);
    const activeClasses = instructionalClasses.filter((row) => row.is_active);
    const activeClusters = clusters.filter((row) => row.is_active);
    lastClusters = activeClusters;
    fillSelect($("timetable-lesson-form").elements.instructional_class_id, activeClasses, (row) => `${row.code} · ${row.name}`);
    fillSelect($("timetable-lesson-form").elements.teacher_id, activeTeachers, (row) => `${row.short_code} · ${row.full_name}`);
    fillSelect($("timetable-lesson-form").elements.subject_id, activeSubjects, (row) => `${row.code} · ${row.name}`);
    fillSelect($("timetable-cluster-member-form").elements.cluster_id, activeClusters, (row) => `${row.code} · ${row.name}`);
    fillSelect($("timetable-cluster-member-form").elements.instructional_class_id, activeClasses, (row) => `${row.code} · ${row.name}`);
    fillSelect($("timetable-period-form").elements.target_id, activeClasses, (row) => `${row.code} · ${row.name}`);
    fillSelect($("timetable-rule-form").elements.target_id, activeClasses, (row) => `${row.code} · ${row.name}`);
    fillSelect($("student-class-mapping-form").elements.instructional_class_id, activeClasses, (row) => `${row.code} · ${row.name}`);
    $("student-class-mapping-form").hidden = !["IT Administrator", "Superuser"].includes(currentRole());
    fillSelect($("attendance-class-mapping-form").elements.instructional_class_id, activeClasses, (row) => `${row.code} · ${row.name}`);
    $("attendance-class-mapping-form").hidden = !canConfigure;
    for (const [id, values] of [["timetable-teacher-rows", teacherRows], ["timetable-subject-rows", subjects], ["timetable-class-rows", instructionalClasses]]) {
      const body = $(id);
      body.replaceChildren();
      for (const item of values) {
        const row = document.createElement("tr");
        const code = item.short_code || item.code;
        for (const value of [code, item.full_name || item.name, item.is_active ? "Active" : "Inactive"]) cell(row, value);
        if (id === "timetable-teacher-rows") {
          const periodsPerWeek = Object.values(item.availability || {}).reduce((sum, day) => sum + (Array.isArray(day) ? day.length : 0), 0);
          cell(row, periodsPerWeek);
        }
        body.append(row);
      }
    }
    const summary = $("timetable-resource-summary");
    if (summary) summary.textContent = `${teacherRows.length} teacher profiles · ${subjects.length} subjects · ${instructionalClasses.length} classes · ${clusters.length} clusters`;
    renderAvailability();
    const periodTable = $("timetable-period-rows");
    periodTable?.replaceChildren();
    if (periodTable) for (const period of periodRows) {
      const row = document.createElement("tr");
      const targets = period.scope === "CLASS" ? instructionalClasses : activeClusters;
      const target = period.scope === "DEFAULT" ? "All classes" : targets.find((item) => item.id === period.target_id)?.code || period.target_id;
      for (const value of [period.scope, target, periodLabels[period.slot_code] || period.slot_code, period.label, period.starts_at ?? "", period.ends_at ?? ""]) cell(row, value);
      const edit = document.createElement("button");
      edit.type = "button";
      edit.className = "secondary";
      edit.textContent = "Edit";
      edit.hidden = !canConfigure;
      edit.addEventListener("click", () => editPeriod(period));
      cell(row, "").append(edit);
      periodTable.append(row);
    }
    const mappingRows = $("student-class-mapping-rows");
    mappingRows.replaceChildren();
    for (const mapping of classMappings) {
      const row = document.createElement("tr");
      cell(row, mapping.source_workbook);
      cell(row, mapping.source_label);
      const classSelect = document.createElement("select");
      classSelect.setAttribute("aria-label", `Target class for ${mapping.source_label}`);
      fillSelect(classSelect, instructionalClasses, (item) => `${item.code} · ${item.name}`);
      classSelect.value = String(mapping.instructional_class_id);
      classSelect.disabled = !["IT Administrator", "Superuser"].includes(currentRole());
      cell(row, "").append(classSelect);
      const active = document.createElement("input");
      active.type = "checkbox";
      active.checked = mapping.is_active;
      active.disabled = !["IT Administrator", "Superuser"].includes(currentRole());
      active.setAttribute("aria-label", `Active mapping for ${mapping.source_label}`);
      cell(row, "").append(active);
      cell(row, String(mapping.version));
      const save = document.createElement("button");
      save.textContent = "Save";
      save.disabled = !["IT Administrator", "Superuser"].includes(currentRole());
      save.setAttribute("aria-label", `Save mapping for ${mapping.source_label}`);
      save.addEventListener("click", () => run(save, async () => {
        const payload = {expected_version: mapping.version};
        if (Number(classSelect.value) !== mapping.instructional_class_id) payload.instructional_class_id = Number(classSelect.value);
        if (active.checked !== mapping.is_active) payload.is_active = active.checked;
        if (Object.keys(payload).length === 1) throw new Error("Change the target class or active status before saving.");
        await api(`/student-reference/class-mappings/${mapping.id}`, "PATCH", payload);
        await refreshSetup();
        notice(`Updated mapping for ${mapping.source_label}.`);
      }));
      cell(row, "").append(save);
      mappingRows.append(row);
    }
    const attendanceMappingRows = $("attendance-class-mapping-rows");
    attendanceMappingRows.replaceChildren();
    for (const mapping of attendanceMappings) {
      const row = document.createElement("tr");
      cell(row, mapping.student_class_name);
      const classSelect = document.createElement("select");
      classSelect.setAttribute("aria-label", `Timetable class for attendance class ${mapping.student_class_name}`);
      fillSelect(classSelect, activeClasses, (item) => `${item.code} · ${item.name}`);
      classSelect.value = String(mapping.instructional_class_id);
      classSelect.disabled = !canConfigure;
      cell(row, "").append(classSelect);
      cell(row, mapping.active_students);
      const active = document.createElement("input");
      active.type = "checkbox";
      active.checked = mapping.is_active;
      active.disabled = !canConfigure;
      active.setAttribute("aria-label", `Active attendance mapping for ${mapping.student_class_name}`);
      cell(row, "").append(active);
      cell(row, mapping.version);
      const save = document.createElement("button");
      save.type = "button";
      save.textContent = "Save";
      save.disabled = !canConfigure;
      save.setAttribute("aria-label", `Save attendance mapping for ${mapping.student_class_name}`);
      save.addEventListener("click", () => run(save, async () => {
        const payload = {expected_version: mapping.version};
        if (Number(classSelect.value) !== mapping.instructional_class_id) payload.instructional_class_id = Number(classSelect.value);
        if (active.checked !== mapping.is_active) payload.is_active = active.checked;
        if (Object.keys(payload).length === 1) throw new Error("Change the mapped class or active status before saving.");
        await api(`/student-reference/attendance-class-mappings/${mapping.id}`, "PATCH", payload);
        await refreshSetup();
        notice(`Updated attendance mapping for ${mapping.student_class_name}.`);
      }));
      cell(row, "").append(save);
      attendanceMappingRows.append(row);
    }
    $("attendance-class-mapping-section").hidden = !["Operator", "IT Administrator", "Superuser"].includes(currentRole());
    updatePeriodTargets();
    updateRuleTargets();
    for (const id of ["timetable-class-form", "timetable-cluster-form", "timetable-cluster-member-form", "timetable-subject-form", "timetable-period-form", "timetable-rule-form"]) $(id).hidden = !canConfigure;
    for (const button of document.querySelectorAll('[data-open-resource-form]')) button.hidden = !canConfigure;
  }

  function updatePeriodTargets() {
    const form = $("timetable-period-form");
    const scope = form.elements.scope.value;
    const targets = scope === "CLASS" ? classes : scope === "CLUSTER" ? lastClusters : [];
    fillSelect(form.elements.target_id, targets, (row) => `${row.code} · ${row.name}`);
    form.elements.target_id.disabled = scope === "DEFAULT";
  }

  let lastClusters = [];
  function updateRuleTargets() {
    const form = $("timetable-rule-form");
    const targets = form.elements.target_type.value === "CLASS" ? classes : lastClusters;
    fillSelect(form.elements.target_id, targets, (row) => `${row.code} · ${row.name}`);
  }

  function availabilityPayload() {
    return Object.fromEntries(weekdays.map((day) => [
      day,
      [...$("teacher-availability").querySelectorAll(`input[data-day="${day}"]:checked`)].map((input) => input.value),
    ]));
  }

  function submitJSON(formId, path, payloadFor, success) {
    const form = $(formId);
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      run(form, async () => {
        const payload = payloadFor(form);
        await api(path, "POST", payload);
        form.reset();
        if (formId === "timetable-teacher-form") {
          for (const input of $("teacher-availability").querySelectorAll('input[type="checkbox"]')) input.checked = true;
        }
        await refresh();
        notice(success);
      });
    });
  }

  submitJSON("timetable-teacher-form", "/timetable/teachers", (form) => ({
    short_code: form.elements.short_code.value,
    full_name: form.elements.full_name.value,
    is_adjunct: form.elements.is_adjunct.checked,
    availability: availabilityPayload(),
  }), "Teacher profile created.");
  submitJSON("timetable-subject-form", "/timetable/subjects", (form) => ({code: form.elements.code.value, name: form.elements.name.value}), "Subject created.");
  submitJSON("timetable-class-form", "/timetable/classes", (form) => ({code: form.elements.code.value, name: form.elements.name.value}), "Instructional class created.");
  $("student-class-mapping-form").addEventListener("submit", (event) => {
    event.preventDefault();
    run(event.currentTarget, async () => {
      const form = event.currentTarget;
      await api("/student-reference/class-mappings", "POST", {
        source_workbook: "STUDENT_INTAKE_2023",
        source_label: form.elements.source_label.value,
        instructional_class_id: Number(form.elements.instructional_class_id.value),
      });
      form.reset();
      await refreshSetup();
      notice("Student intake class mapping saved.");
    });
  });
  $("attendance-class-mapping-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    run(form, async () => {
      const payload = Object.fromEntries(new FormData(form));
      payload.instructional_class_id = Number(payload.instructional_class_id);
      await api("/student-reference/attendance-class-mappings", "POST", payload);
      form.reset();
      await refreshSetup();
      notice("Attendance class mapped to its instructional timetable class.");
    });
  });
  submitJSON("timetable-cluster-form", "/timetable/clusters", (form) => ({code: form.elements.code.value, name: form.elements.name.value}), "Class cluster created.");
  $("timetable-cluster-member-form").addEventListener("submit", (event) => {
    event.preventDefault();
    run(event.currentTarget, async () => {
      const form = event.currentTarget;
      const clusterId = Number(form.elements.cluster_id.value);
      await api(`/timetable/clusters/${clusterId}/classes`, "POST", {instructional_class_id: Number(form.elements.instructional_class_id.value)});
      await refresh();
      notice("Class added to cluster.");
    });
  });
  function editPeriod(period) {
    const form = $("timetable-period-form");
    form.dataset.periodId = String(period.id);
    form.elements.scope.value = period.scope;
    updatePeriodTargets();
    if (period.scope !== "DEFAULT") form.elements.target_id.value = String(period.target_id);
    form.elements.slot_code.value = period.slot_code;
    form.elements.label.value = period.label;
    form.elements.starts_at.value = period.starts_at;
    form.elements.ends_at.value = period.ends_at;
    form.elements.scope.disabled = true;
    form.elements.target_id.disabled = true;
    form.elements.slot_code.disabled = true;
    form.elements.label.disabled = period.slot_code === "LUNCH";
    form.querySelector('button[type="submit"]').textContent = "Update period";
    form.scrollIntoView({behavior: "smooth", block: "center"});
  }

  $("timetable-period-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    run(form, async () => {
      const isEdit = Boolean(form.dataset.periodId);
      const payload = isEdit
        ? {label: form.elements.label.value, starts_at: form.elements.starts_at.value, ends_at: form.elements.ends_at.value}
        : {
            scope: form.elements.scope.value,
            target_id: form.elements.scope.value === "DEFAULT" ? null : Number(form.elements.target_id.value),
            slot_code: form.elements.slot_code.value,
            label: form.elements.label.value,
            starts_at: form.elements.starts_at.value,
            ends_at: form.elements.ends_at.value,
          };
      await api(isEdit ? `/timetable/periods/${form.dataset.periodId}` : "/timetable/periods", isEdit ? "PATCH" : "POST", payload);
      delete form.dataset.periodId;
      form.reset();
      form.elements.scope.disabled = false;
      form.elements.target_id.disabled = false;
      form.elements.slot_code.disabled = false;
      form.elements.label.disabled = false;
      form.querySelector('button[type="submit"]').textContent = "Save period definition";
      updatePeriodTargets();
      await refresh();
      notice(isEdit ? "Period definition updated." : "Period definition saved for future timetable drafts.");
    });
  });
  submitJSON("timetable-rule-form", "/timetable/rules", (form) => ({
    academic_year: form.elements.academic_year.value,
    target_type: form.elements.target_type.value,
    target_id: Number(form.elements.target_id.value),
    effective_from: form.elements.effective_from.value,
    effective_to: form.elements.effective_to.value || null,
    rule: {
      schema_version: 1,
      max_lessons_per_day: Number(form.elements.max_lessons_per_day.value),
      allowed_days: [...form.elements.allowed_days.selectedOptions].map((option) => option.value),
      allowed_periods: [...form.elements.allowed_periods.selectedOptions].map((option) => option.value),
    },
  }), "Scheduling rule saved.");
  submitJSON("timetable-lesson-form", "/timetable/lessons", (form) => ({
    academic_year: form.elements.academic_year.value,
    instructional_class_id: Number(form.elements.instructional_class_id.value),
    teacher_id: Number(form.elements.teacher_id.value),
    subject_id: Number(form.elements.subject_id.value),
    weekly_count: Number(form.elements.weekly_count.value),
    block_length: Number(form.elements.block_length.value),
  }), "Weekly lesson requirement saved.");

  async function show() {
    showPanel("timetable");
    await refresh();
  }

  function labelFor(block) {
    const requirement = current.snapshot.requirements[String(block.lesson_requirement_id)];
    const teacher = current.snapshot.teachers[String(requirement.teacher_id)];
    const subject = current.snapshot.subjects[String(requirement.subject_id)];
    return `${subject.code} · ${teacher.short_code}${block.is_locked ? " · locked" : ""}`;
  }

  function requirementLabel(id) {
    const requirement = current.snapshot.requirements[String(id)];
    const teacher = current.snapshot.teachers[String(requirement.teacher_id)];
    const subject = current.snapshot.subjects[String(requirement.subject_id)];
    const classItem = current.snapshot.classes[String(requirement.instructional_class_id)];
    return `${classItem.code} · ${subject.name} · ${teacher.full_name} · ${requirement.weekly_count}/week`;
  }

  function classRows() {
    return Object.values(current.snapshot.classes).sort((a, b) => a.reporting_order - b.reporting_order || a.code.localeCompare(b.code));
  }

  function renderGrid() {
    const host = $("timetable-grid");
    host.replaceChildren();
    host.classList.remove("weekly-board-host");
    if (!current) return;
    const amendMode = $("timetable-board-mode").value === "amend";
    $("timetable-editor").classList.toggle("amend-mode", amendMode);
    document.querySelector(".timetable-board-layout").classList.toggle("amend-mode", amendMode);
    $("timetable-density").parentElement.hidden = !amendMode;
    $("timetable-previous").hidden = !amendMode;
    $("timetable-next").hidden = !amendMode;
    if (current && !amendMode) {
      renderWeeklyBoard(host);
      if (draftMutationPending) {
        for (const button of host.querySelectorAll("button")) button.disabled = true;
      }
      return;
    }
    $("timetable-summary").hidden = true;
    const all = classRows();
    const density = Number($("timetable-density").value) || 4;
    const visible = all.slice(pageOffset, pageOffset + density);
    $("timetable-previous").disabled = pageOffset === 0;
    $("timetable-next").disabled = pageOffset + density >= all.length;
    for (const classItem of visible) {
      const panel = document.createElement("section");
      panel.className = "panel timetable-class";
      const heading = document.createElement("h4");
      heading.textContent = `${classItem.code} · ${classItem.name}`;
      panel.append(heading);
      const wrap = document.createElement("div");
      wrap.className = "table-wrap";
      const table = document.createElement("table");
      table.className = "amend-grid";
      const head = document.createElement("thead");
      const headerRow = document.createElement("tr");
      cell(headerRow, "Day");
      for (const period of periods) cell(headerRow, periodLabels[period]);
      head.append(headerRow);
      table.append(head);
      const body = document.createElement("tbody");
      for (const day of weekdays) {
        const row = document.createElement("tr");
        cell(row, day);
        for (const period of periods) {
          const td = cell(row, "");
          if (period === "LUNCH") {
            td.className = "lunch-cell";
            td.textContent = "Lunch";
            continue;
          }
          const placement = current.placements.find((block) => block.slots.some((slot) =>
            slot.instructional_class_id === classItem.id && slot.weekday === day && slot.slot_code === period));
          const button = document.createElement("button");
          button.className = placement ? "lesson-cell" : "empty-cell";
          button.disabled = !editableDraft() || draftMutationPending;
          button.textContent = placement ? labelFor(placement) : (editableDraft() ? "+ Add lesson" : "—");
          button.setAttribute("aria-label", placement
            ? `${classItem.code} ${day} ${periodLabels[period]} ${labelFor(placement)}`
            : `Add lesson to ${classItem.code} ${day} ${periodLabels[period]}`);
          if (placement) button.addEventListener("click", () => editPlacement(placement, day, period));
          else if (editableDraft()) button.addEventListener("click", () => run(button, () => addPlacement(classItem, day, period)));
          td.append(button);
        }
        body.append(row);
      }
      table.append(body);
      wrap.append(table);
      panel.append(wrap);
      host.append(panel);
    }
    if (!visible.length) host.textContent = "This timetable has no selected classes.";
  }

  function renderWeeklyBoard(host) {
    const search = $("timetable-search").value.trim().toLocaleLowerCase();
    const selectedId = Number(viewBy === "class" ? $("timetable-class-filter").value : $("timetable-teacher-filter").value);
    const entity = viewBy === "class"
      ? current.snapshot.classes[String(selectedId)]
      : current.snapshot.teachers[String(selectedId)];
    $("timetable-summary").replaceChildren();
    $("timetable-summary").hidden = false;
    host.classList.add("weekly-board-host");
    if (!entity || (search && !`${entity.code || entity.short_code} ${entity.name || entity.full_name}`.toLocaleLowerCase().includes(search))) {
      host.textContent = "Choose an available class or teacher to view its timetable.";
      return;
    }
    const title = document.createElement("h3");
    title.textContent = viewBy === "class" ? `${entity.code} · ${entity.name}` : `${entity.short_code} · ${entity.full_name}`;
    host.append(title);
    const table = document.createElement("table");
    table.className = "weekly-board";
    const thead = document.createElement("thead");
    const header = document.createElement("tr");
    cell(header, "Period");
    for (const day of weekdays) cell(header, day[0] + day.slice(1).toLowerCase());
    thead.append(header);
    table.append(thead);
    const tbody = document.createElement("tbody");
    for (const period of periods) {
      const row = document.createElement("tr");
      const label = document.createElement("th");
      label.scope = "row";
      label.textContent = periodLabels[period];
      row.append(label);
      for (const day of weekdays) {
        const td = document.createElement("td");
        if (period === "LUNCH") {
          td.className = "lunch-cell";
          td.textContent = "Lunch / Muster";
          row.append(td);
          continue;
        }
        const block = current.placements.find((candidate) => {
          const req = current.snapshot.requirements[String(candidate.lesson_requirement_id)];
          const matchesEntity = viewBy === "class"
            ? req?.instructional_class_id === entity.id
            : req?.teacher_id === entity.id;
          return matchesEntity && candidate.slots.some((slot) => slot.weekday === day && slot.slot_code === period);
        });
        const button = document.createElement("button");
        if (block) {
          button.className = "lesson-cell weekly-lesson";
          button.textContent = labelFor(block);
          button.setAttribute("aria-label", `${title.textContent} ${day} ${periodLabels[period]} ${labelFor(block)}`);
          button.addEventListener("click", () => editPlacement(block, block.weekday, block.start_period));
        } else if (viewBy === "teacher") {
          button.className = "free-cell";
          button.textContent = "Free";
          button.disabled = !editableDraft() || draftMutationPending;
          if (editableDraft()) button.addEventListener("click", () => addTeacherPlacement(entity, day, period));
        } else {
          button.className = "empty-cell";
          button.textContent = editableDraft() ? "+ Add lesson" : "—";
          button.disabled = !editableDraft();
          if (editableDraft()) button.addEventListener("click", () => run(button, () => addPlacement(entity, day, period)));
        }
        td.append(button);
        row.append(td);
      }
      tbody.append(row);
    }
    table.append(tbody);
    host.append(table);
    if (viewBy === "teacher") renderTeacherSummary(entity);
  }

  function addTeacherPlacement(teacher, weekday, startPeriod) {
    const pending = current.pending.filter((item) => current.snapshot.requirements[String(item.lesson_requirement_id)]?.teacher_id === teacher.id);
    if (!pending.length) {
      notice(`No unplaced lesson requirements remain for ${teacher.full_name}.`);
      return;
    }
    const requirement = current.snapshot.requirements[String(pending[0].lesson_requirement_id)];
    const classItem = current.snapshot.classes[String(requirement.instructional_class_id)];
    const ids = pending.map((item) => item.lesson_requirement_id);
    const lengths = pending.flatMap((item) => item.remaining_blocks);
    openPlacement(ids, {class_code: classItem.code, weekday, start_period: startPeriod, allowed_lengths: lengths});
  }

  function renderTeacherSummary(teacher) {
    const placements = current.placements.filter((block) => current.snapshot.requirements[String(block.lesson_requirement_id)]?.teacher_id === teacher.id);
    const taught = placements.reduce((sum, block) => sum + block.period_count, 0);
    const scheduledSlots = weekdays.length * periods.filter((p) => p !== "LUNCH").length;
    const free = Math.max(0, scheduledSlots - taught);
    const classNames = [...new Set(placements.map((block) => {
      const req = current.snapshot.requirements[String(block.lesson_requirement_id)];
      return current.snapshot.classes[String(req.instructional_class_id)]?.code;
    }).filter(Boolean))];
    for (const [label, value] of [["Periods taught", taught], ["Free periods", free], ["Duty periods", 0], ["Classes", classNames.length]]) {
      const card = document.createElement("div");
      card.className = "teacher-stat";
      const strong = document.createElement("strong");
      strong.textContent = String(value);
      const caption = document.createElement("span");
      caption.textContent = label;
      card.append(strong, caption);
      $("timetable-summary").append(card);
    }
    const note = document.createElement("p");
    note.textContent = `Classes taught: ${classNames.join(", ") || "None assigned"}`;
    $("timetable-summary").append(note);
  }

  function printReports(kind) {
    if (!current) {
      notice("Open a saved timetable draft before exporting reports.");
      return;
    }
    const escapeHTML = (value) => String(value ?? "").replace(/[&<>\"']/g, (char) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;"}[char]));
    const includeLunch = $("print-lunch-row").checked;
    const includeAllPeriods = $("print-all-periods").checked;
    const periodOrder = ["P1", "P2", "LUNCH", "P3", "P4"];
    const periodNumber = {P1: 1, P2: 2, LUNCH: 3, P3: 4, P4: 5};
    const dayLabels = {MON: "Mo", TUE: "Tu", WED: "We", THU: "Th", FRI: "Fr"};
    const days = Object.keys(dayLabels);
    const classes = classRows();
    const items = [];
    if (kind !== "teacher") {
      for (const cls of classes) items.push({kind: "class", item: cls});
    }
    if (kind !== "class") {
      for (const teacher of Object.values(current.snapshot.teachers).sort((a, b) => a.short_code.localeCompare(b.short_code))) items.push({kind: "teacher", item: teacher});
    }
    if (!items.length) {
      notice("There are no class or teacher schedules in this timetable.");
      return;
    }
    const getPeriodDefinitions = (itemKind, item) => {
      if (itemKind === "class") return [item.periods ?? []];
      return classes.map((classItem) => classItem.periods ?? []);
    };
    const formatTime = (value) => {
      if (!value) return "";
      const [hours, minutes] = value.slice(0, 5).split(":");
      return `${Number(hours)}:${minutes}`;
    };
    const formatDate = (value) => {
      if (!value) return "Not recorded";
      const date = new Date(value);
      return Number.isNaN(date.getTime()) ? "Not recorded" : new Intl.DateTimeFormat("en-SG", {dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Singapore"}).format(date);
    };
    const generatedAt = new Intl.DateTimeFormat("en-SG", {dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Singapore"}).format(new Date());
    const sections = items.map(({kind: itemKind, item}) => {
      const title = itemKind === "class" ? item.code : `Teacher ${item.full_name}`;
      const periodDefinitions = getPeriodDefinitions(itemKind, item);
      const periodsToPrint = periodOrder.filter((period) => {
        if (period === "LUNCH" && !includeLunch) return false;
        if (includeAllPeriods || period === "LUNCH") return true;
        return current.placements.some((candidate) => {
          const req = current.snapshot.requirements[String(candidate.lesson_requirement_id)];
          const matches = itemKind === "class" ? req?.instructional_class_id === item.id : req?.teacher_id === item.id;
          return matches && candidate.slots.some((slot) => slot.slot_code === period);
        });
      });
      const periodHeaders = periodsToPrint.map((period) => {
        const definitions = periodDefinitions.map((rows) => rows.find((row) => row.slot_code === period)).filter(Boolean);
        const times = [...new Set(definitions.map((row) => `${row.starts_at ?? ""}-${row.ends_at ?? ""}`))];
        const timeText = !times.length || times.every((value) => value === "-")
          ? "Time not set"
          : times.length > 1
            ? "Times vary by class"
            : `${formatTime(definitions[0].starts_at)} – ${formatTime(definitions[0].ends_at)}`;
        const label = period === "LUNCH" ? "Lunch / Muster" : `Period ${periodNumber[period]}`;
        return `<th data-period="${period}"><span>${label}</span><small>${escapeHTML(timeText)}</small></th>`;
      }).join("");
      const rows = days.map((day) => {
        const cells = periodsToPrint.map((period) => {
          if (period === "LUNCH") return '<td class="lunch-cell" data-period="LUNCH">Lunch / Muster</td>';
          const entries = current.placements.flatMap((candidate) => {
            const req = current.snapshot.requirements[String(candidate.lesson_requirement_id)];
            const matches = itemKind === "class" ? req?.instructional_class_id === item.id : req?.teacher_id === item.id;
            if (!matches) return [];
            return candidate.slots.filter((slot) => slot.weekday === day && slot.slot_code === period).map((slot) => ({req, slot}));
          });
          const content = entries.map(({req, slot}) => {
            const subject = current.snapshot.subjects[String(req.subject_id)];
            const classItem = current.snapshot.classes[String(req.instructional_class_id)];
            const teacher = current.snapshot.teachers[String(req.teacher_id)];
            const resource = itemKind === "class" ? teacher.short_code : classItem.code;
            const timeVaries = itemKind === "teacher" && periodDefinitions
              .map((definitions) => definitions.find((definition) => definition.slot_code === period))
              .filter(Boolean)
              .some((definition, index, definitions) => index > 0 && (definition.starts_at !== definitions[0].starts_at || definition.ends_at !== definitions[0].ends_at));
            const time = timeVaries ? `<small class="entry-time">${formatTime(slot.starts_at)} – ${formatTime(slot.ends_at)}</small>` : "";
            return `<span class="lesson-entry"><strong>${escapeHTML(subject.name)}</strong><small class="entry-resource">${escapeHTML(resource)}</small>${time}</span>`;
          }).join("");
          return `<td data-period="${period}">${content}</td>`;
        }).join("");
        return `<tr data-weekday="${day}"><th scope="row">${dayLabels[day]}</th>${cells}</tr>`;
      }).join("");
      const className = itemKind === "class" ? `<span>${escapeHTML(item.name)}</span>` : "";
      return `<section class="report-page" data-report-kind="${itemKind}"><header class="report-header"><div class="report-brand"><img src="/ui/sps-crest.png" alt=""><strong>Singapore Prison Service</strong></div><div class="report-title"><h1>${escapeHTML(title)}</h1>${className}<p>Academic year ${escapeHTML(current.academic_year)} · Week of ${escapeHTML(current.week_start)}</p><p>${escapeHTML(current.status)} · Revision ${escapeHTML(current.revision)}</p></div></header><table class="report-table"><thead><tr><th class="day-heading"></th>${periodHeaders}</tr></thead><tbody>${rows}</tbody></table><footer class="report-footer"><span>Timetable generated on ${escapeHTML(generatedAt)}</span><span>Prison School Timetables</span></footer></section>`;
    }).join("");
    const printWindow = window.open("", "_blank");
    if (!printWindow) {
      notice("Allow pop-ups for this site to export timetable reports.");
      return;
    }
    printWindow.opener = null;
    printWindow.document.write(`<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${escapeHTML(current.name)} · Timetable report</title><link rel="stylesheet" href="/ui/timetable-print.css"></head><body>${sections}</body></html>`);
    printWindow.addEventListener("load", () => printWindow.print(), {once: true});
    printWindow.document.close();
  }

  function renderPending() {
    const rows = $("timetable-pending");
    rows.replaceChildren();
    for (const pending of current.pending) {
      const requirement = current.snapshot.requirements[String(pending.lesson_requirement_id)];
      const teacher = current.snapshot.teachers[String(requirement.teacher_id)];
      const subject = current.snapshot.subjects[String(requirement.subject_id)];
      const classItem = current.snapshot.classes[String(requirement.instructional_class_id)];
      const row = document.createElement("tr");
      for (const value of [classItem.name, subject.name, teacher.full_name, pending.remaining_periods, pending.remaining_blocks.join(", ")]) cell(row, value);
      rows.append(row);
    }
    if (!current.pending.length) {
      const row = document.createElement("tr");
      cell(row, "All weekly lesson requirements are placed.").colSpan = 5;
      rows.append(row);
    }
  }

  function render() {
    if (!current) return;
    fillSelect($("timetable-class-filter"), Object.values(current.snapshot.classes).sort((a, b) => a.reporting_order - b.reporting_order), (row) => `${row.code} · ${row.name}`);
    fillSelect($("timetable-teacher-filter"), Object.values(current.snapshot.teachers).sort((a, b) => a.short_code.localeCompare(b.short_code)), (row) => `${row.short_code} · ${row.full_name}`);
    $("timetable-editor").hidden = false;
    $("timetable-editor-title").textContent = current.name;
    $("timetable-version-detail").textContent = `${current.academic_year} · week of ${current.week_start} · ${current.status} · revision ${current.revision}`;
    if (current.is_published) $("timetable-version-detail").textContent += " · PUBLISHED";
    $("timetable-generate").hidden = !editableDraft();
    $("timetable-generation-mode").disabled = !editableDraft();
    $("timetable-search-budget").disabled = !editableDraft();
    $("timetable-approve").hidden = !canApprove() || current.status !== "DRAFT";
    $("timetable-publish").hidden = !canApprove() || current.status !== "APPROVED" || current.is_published;
    $("timetable-unpublish").hidden = !canApprove() || !current.is_published;
    renderGrid();
    renderPending();
    syncDraftMutationControls();
  }

  async function load(id) {
    const sequence = ++detailSequence;
    const result = await api(`/timetable/versions/${id}`);
    if (sequence !== detailSequence) return;
    current = result;
    placementForm.hidden = true;
    $("timetable-generation-summary").textContent = "";
    pageOffset = 0;
    render();
  }

  function openPlacement(requirementOptions, values, isEdit = false) {
    const form = placementForm;
    form.reset();
    form.hidden = false;
    form.elements.placement_id.value = values.placement_id || "";
    form.elements.weekday.value = values.weekday;
    form.elements.start_period.value = values.start_period;
    form.elements.note.value = values.note || "";
    $("timetable-placement-title").textContent = isEdit ? "Amend lesson block" : "Add lesson block";
    $("timetable-placement-location").textContent = `${values.class_code} · ${values.weekday} · ${values.start_period}`;
    const reqSelect = form.elements.lesson_requirement_id;
    reqSelect.replaceChildren();
    for (const id of requirementOptions) {
      const option = document.createElement("option");
      option.value = id;
      option.textContent = requirementLabel(id);
      reqSelect.append(option);
    }
    if (values.lesson_requirement_id) reqSelect.value = String(values.lesson_requirement_id);
    const lengthSelect = form.elements.period_count;
    lengthSelect.replaceChildren();
    const lengths = new Set(values.allowed_lengths || [1]);
    if (values.period_count) lengths.add(values.period_count);
    for (const length of [...lengths].sort((a, b) => a - b)) {
      const option = document.createElement("option");
      option.value = length;
      option.textContent = `${length} period${length === 1 ? "" : "s"}`;
      lengthSelect.append(option);
    }
    if (values.period_count) lengthSelect.value = String(values.period_count);
    $("timetable-remove").hidden = !isEdit;
    $("timetable-lock").hidden = !isEdit;
    $("timetable-lock").textContent = values.is_locked ? "Unlock lesson" : "Lock lesson";
    $("timetable-lock").dataset.locked = String(values.is_locked || false);
    form.elements.lesson_requirement_id.disabled = !editableDraft();
    form.elements.period_count.disabled = !editableDraft();
    form.elements.note.disabled = !editableDraft();
    form.querySelector('[type="submit"]').hidden = !editableDraft();
    syncDraftMutationControls();
    form.elements.lesson_requirement_id.focus();
  }

  function addPlacement(classItem, weekday, startPeriod) {
    const pending = current.pending.filter((item) => {
      const requirement = current.snapshot.requirements[String(item.lesson_requirement_id)];
      const requirementClass = current.snapshot.classes[String(requirement?.instructional_class_id)];
      return requirementClass?.code === classItem.code;
    });
    if (!pending.length) {
      notice(`No unplaced requirements remain for ${classItem.name}.`);
      return;
    }
    const ids = pending.map((item) => item.lesson_requirement_id);
    const lengths = pending.flatMap((item) => item.remaining_blocks);
    openPlacement(ids, {class_code: classItem.code, weekday, start_period: startPeriod, allowed_lengths: lengths});
  }

  function editPlacement(placement, weekday, startPeriod) {
    const classId = placement.slots.find((slot) => slot.weekday === weekday && slot.slot_code === startPeriod)?.instructional_class_id;
    const classItem = current.snapshot.classes[String(classId)];
    const pendingIds = new Set(current.pending.map((row) => row.lesson_requirement_id));
    const ids = Object.values(current.snapshot.requirements)
      .filter((item) => item.instructional_class_id === classId && (item.id === placement.lesson_requirement_id || pendingIds.has(item.id)))
      .map((item) => item.id);
    openPlacement(ids, {
      placement_id: placement.id, lesson_requirement_id: placement.lesson_requirement_id,
      weekday: placement.weekday, start_period: placement.start_period, period_count: placement.period_count,
      note: placement.note, is_locked: placement.is_locked, class_code: classItem.code,
      allowed_lengths: [placement.period_count],
    }, true);
  }

  async function savePlacement(event) {
    event.preventDefault();
    const form = placementForm;
    const placementId = form.elements.placement_id.value;
    const payload = {
      expected_revision: current.revision,
      lesson_requirement_id: Number(form.elements.lesson_requirement_id.value),
      weekday: form.elements.weekday.value,
      start_period: form.elements.start_period.value,
      period_count: Number(form.elements.period_count.value),
      note: form.elements.note.value,
    };
    current = await api(placementId
      ? `/timetable/versions/${current.id}/placements/${placementId}`
      : `/timetable/versions/${current.id}/placements`, placementId ? "PUT" : "POST", payload);
    form.hidden = true;
    render();
    notice("Lesson saved to the timetable draft.");
  }

  async function removePlacement() {
    const id = placementForm.elements.placement_id.value;
    current = await api(`/timetable/versions/${current.id}/placements/${id}?expected_revision=${current.revision}`, "DELETE");
    placementForm.hidden = true;
    render();
    notice("Lesson removed from the draft.");
  }

  async function toggleLock() {
    const id = placementForm.elements.placement_id.value;
    const isLocked = placementForm.querySelector("#timetable-lock").dataset.locked !== "true";
    current = await api(`/timetable/versions/${current.id}/placements/${id}/lock`, "PATCH", {expected_revision: current.revision, is_locked: isLocked});
    placementForm.hidden = true;
    render();
    notice(isLocked ? "Lesson locked." : "Lesson unlocked.");
  }

  async function generate() {
    if (!current || current.status !== "DRAFT") return;
    const mode = $("timetable-generation-mode").value;
    if (mode === "REPLACE_UNLOCKED" && !window.confirm("Replace all unlocked lesson blocks in this draft? Locked blocks will remain.")) return;
    const result = await api(`/timetable/versions/${current.id}/generate`, "POST", {
      expected_revision: current.revision,
      mode,
      search_budget: Number($("timetable-search-budget").value),
    });
    current = result.timetable;
    const report = result.generation;
    $("timetable-generation-summary").textContent = report.complete
      ? `Generation complete: ${report.generated_periods} periods added. Draft revision ${current.revision}.`
      : `Generation placed ${report.generated_periods} periods. ${report.unplaced.length} blocks remain; review the pending list. Search limit reached: ${report.search_limit_reached ? "yes" : "no"}.`;
    render();
  }

  async function approve() {
    current = await api(`/timetable/versions/${current.id}/approve`, "POST", {expected_revision: current.revision});
    render();
    await refresh();
    notice("Timetable approved and saved as an immutable version.");
  }

  async function publish() {
    current = await api(`/timetable/versions/${current.id}/publish`, "POST", {expected_revision: current.revision});
    render();
    await refresh();
    notice("Approved timetable published for this academic week.");
  }

  async function unpublish() {
    current = await api(`/timetable/versions/${current.id}/unpublish`, "POST", {expected_revision: current.revision});
    render();
    await refresh();
    notice("Timetable unpublished. No version is currently published for this week.");
  }

  $("timetable-create-form").addEventListener("submit", (event) => {
    event.preventDefault();
    run(event.currentTarget, async () => {
      const form = event.currentTarget;
      const payload = {
        name: form.elements.name.value,
        academic_year: form.elements.academic_year.value,
        week_start: form.elements.week_start.value,
        class_ids: [...form.elements.class_ids.selectedOptions].map((option) => Number(option.value)),
      };
      current = await api("/timetable/versions", "POST", payload);
      form.hidden = true;
      await refresh();
      render();
      notice("Weekly timetable draft created.");
    });
  });
  placementForm.addEventListener("submit", (event) => {
    event.preventDefault();
    runDraftMutation(placementForm, () => savePlacement(event));
  });
  $("timetable-remove").addEventListener("click", () => runDraftMutation($("timetable-remove"), removePlacement));
  $("timetable-lock").addEventListener("click", () => runDraftMutation($("timetable-lock"), toggleLock));
  $("timetable-cancel-placement").addEventListener("click", () => { placementForm.hidden = true; });
  $("timetable-generate").addEventListener("click", () => runDraftMutation($("timetable-generate"), generate));
  $("timetable-approve").addEventListener("click", () => runDraftMutation($("timetable-approve"), approve));
  $("timetable-download-report").addEventListener("click", () => run($("timetable-download-report"), () =>
    downloadXlsx(`/timetable/versions/${current.id}/reports.xlsx?kind=both`)));
  $("timetable-publish").addEventListener("click", () => run($("timetable-publish"), publish));
  $("timetable-unpublish").addEventListener("click", () => run($("timetable-unpublish"), unpublish));
  $("new-timetable").addEventListener("click", () => {
    const form = $("timetable-create-form");
    form.hidden = !form.hidden;
    if (!form.hidden) form.elements.name.focus();
  });
  $("refresh-timetables").addEventListener("click", () => run($("refresh-timetables"), refresh));
  $("timetable-reload").addEventListener("click", () => run($("timetable-reload"), () => load(current.id)));
  $("timetable-density").addEventListener("change", renderGrid);
  $("timetable-period-form").elements.scope.addEventListener("change", updatePeriodTargets);
  $("timetable-period-form").elements.slot_code.addEventListener("change", () => {
    const isLunch = $("timetable-period-form").elements.slot_code.value === "LUNCH";
    const label = $("timetable-period-form").elements.label;
    if (isLunch) label.value = "LUNCH";
    label.disabled = isLunch;
  });
  $("timetable-rule-form").elements.target_type.addEventListener("change", updateRuleTargets);
  $("timetable-previous").addEventListener("click", () => { pageOffset = Math.max(0, pageOffset - Number($("timetable-density").value)); renderGrid(); });
  $("timetable-next").addEventListener("click", () => { pageOffset += Number($("timetable-density").value); renderGrid(); });

  function chooseView(view) {
    viewBy = view;
    $("timetable-by-class").classList.toggle("is-selected", view === "class");
    $("timetable-by-teacher").classList.toggle("is-selected", view === "teacher");
    $("timetable-class-filter-wrap").hidden = view !== "class";
    $("timetable-teacher-filter-wrap").hidden = view !== "teacher";
    renderGrid();
  }
  $("timetable-by-class").addEventListener("click", () => chooseView("class"));
  $("timetable-by-teacher").addEventListener("click", () => chooseView("teacher"));
  for (const id of ["timetable-class-filter", "timetable-teacher-filter", "timetable-search", "timetable-board-mode"]) {
    $(id).addEventListener("input", renderGrid);
    $(id).addEventListener("change", renderGrid);
  }
  $("timetable-print").addEventListener("click", () => printReports(viewBy));
  for (const button of document.querySelectorAll("[data-print-report]")) {
    button.addEventListener("click", () => printReports(button.dataset.printReport));
  }
  $("timetable-print-both").addEventListener("click", () => printReports("both"));
  for (const button of document.querySelectorAll("[data-timetable-page]")) {
    button.addEventListener("click", () => {
      const target = button.dataset.timetablePage;
      for (const page of document.querySelectorAll(".timetable-page")) page.hidden = page.id !== `timetable-${target}-page`;
      for (const link of document.querySelectorAll(".timetable-side-link")) link.classList.toggle("is-active", link === button);
    });
  }
  for (const button of document.querySelectorAll("[data-resource-tab]")) {
    button.addEventListener("click", () => {
      const target = button.dataset.resourceTab;
      for (const tab of document.querySelectorAll("[data-resource-tab]")) tab.classList.toggle("is-selected", tab === button);
      for (const panel of document.querySelectorAll("[data-resource-panel]")) panel.hidden = panel.dataset.resourcePanel !== target;
    });
  }
  for (const button of document.querySelectorAll("[data-open-resource-form]")) {
    button.addEventListener("click", () => {
      const form = $(button.dataset.openResourceForm);
      form.hidden = false;
      form.scrollIntoView({behavior: "smooth", block: "center"});
      form.querySelector("input")?.focus();
    });
  }
  $("teacher-search").addEventListener("input", () => {
    const query = $("teacher-search").value.trim().toLocaleLowerCase();
    for (const row of $("timetable-teacher-rows").rows) row.hidden = !row.textContent.toLocaleLowerCase().includes(query);
  });

  return {show, clear};
}
