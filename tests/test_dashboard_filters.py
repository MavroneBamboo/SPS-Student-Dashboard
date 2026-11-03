from uuid import uuid4


def test_dashboard_filters_current_profiles_by_category_institution_status_and_year(lesson_context):
    client, headers, _ = lesson_context
    suffix = uuid4().hex[:8].upper()
    category_a = client.post(
        "/api/v1/student-reference/categories",
        json={"code": f"DASH-{suffix}-A", "name": "Dashboard category A"},
        headers=headers["admin"],
    ).json()
    category_b = client.post(
        "/api/v1/student-reference/categories",
        json={"code": f"DASH-{suffix}-B", "name": "Dashboard category B"},
        headers=headers["admin"],
    ).json()
    institution_a = client.post(
        "/api/v1/student-reference/institutions",
        json={"code": f"DASHI-{suffix}-A", "name": "Dashboard institution A"},
        headers=headers["admin"],
    ).json()
    institution_b = client.post(
        "/api/v1/student-reference/institutions",
        json={"code": f"DASHI-{suffix}-B", "name": "Dashboard institution B"},
        headers=headers["admin"],
    ).json()

    profiles = [
        {
            "pris_no": f"DASH-{suffix}-1",
            "name": "Active category A profile",
            "class_name": f"Dashboard class A {suffix}",
            "category": category_a["code"],
            "institution_id": institution_a["id"],
            "status": "ACTIVE",
            "academic_year": "2026",
            "age_in_academic_year": 30,
        },
        {
            "pris_no": f"DASH-{suffix}-2",
            "name": "Inactive category A profile",
            "class_name": f"Dashboard class B {suffix}",
            "category": category_a["code"],
            "institution_id": institution_b["id"],
            "status": "INACTIVE",
            "academic_year": "2025",
        },
        {
            "pris_no": f"DASH-{suffix}-3",
            "name": "Active category B profile",
            "class_name": f"Dashboard class C {suffix}",
            "category": category_b["code"],
            "institution_id": institution_a["id"],
            "status": "ACTIVE",
            "academic_year": "2026",
            "age_in_academic_year": 21,
        },
    ]
    for profile in profiles:
        created = client.post("/api/v1/students", json=profile, headers=headers["operator"])
        assert created.status_code == 201, created.text

    filtered = client.get(
        "/api/v1/reports/dashboard",
        params={
            "category_id": category_a["id"],
            "institution_id": institution_a["id"],
            "student_status": " active ",
            "academic_year": "2026",
            "class_name": profiles[0]["class_name"],
        },
        headers=headers["executive"],
    )
    assert filtered.status_code == 200, filtered.text
    result = filtered.json()
    assert result["students"] == {
        "total": 1,
        "active": 1,
        "by_class": {profiles[0]["class_name"]: 1},
        "by_category": {category_a["code"]: 1},
        "by_institution": {"Dashboard institution A": 1},
        "by_age": {"2026 · 30": 1},
    }
    assert result["filters"] == {
        "class_name": profiles[0]["class_name"],
        "category_id": category_a["id"],
        "institution_id": institution_a["id"],
        "student_status": "ACTIVE",
        "academic_year": "2026",
        "date_from": None,
        "date_to": None,
    }

    inactive = client.get(
        "/api/v1/reports/dashboard",
        params={"category_id": category_a["id"], "student_status": "INACTIVE"},
        headers=headers["operator"],
    )
    assert inactive.status_code == 200
    assert inactive.json()["students"]["total"] == 1
    assert inactive.json()["students"]["active"] == 0
    assert inactive.json()["students"]["by_class"] == {}
    assert inactive.json()["students"]["by_institution"] == {}
