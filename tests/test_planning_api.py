"""Thin tests confirming GET /plan wires up correctly and serializes right.

The detailed planning rules are already covered by test_planning_service.py
against a fixed reference date; these just confirm the HTTP wiring, using
the real `today` since the API does not expose a way to override it.
"""

from datetime import date, timedelta

from fastapi.testclient import TestClient

TODAY = date.today()
YESTERDAY = TODAY - timedelta(days=1)


def test_get_plan_with_no_data_returns_empty_snapshot(client: TestClient) -> None:
    response = client.get("/plan")

    assert response.status_code == 200
    body = response.json()
    assert body["reference_date"] == TODAY.isoformat()
    assert body["relevant_tasks"] == []
    assert body["overdue_tasks"] == []
    assert body["goals_falling_behind"] == []
    assert body["suggested_task"] is None


def test_get_plan_includes_overdue_task(client: TestClient) -> None:
    created = client.post(
        "/tasks", json={"title": "Overdue task", "due_date": YESTERDAY.isoformat()}
    ).json()

    response = client.get("/plan")

    assert response.status_code == 200
    body = response.json()
    overdue_ids = [task["id"] for task in body["overdue_tasks"]]
    assert created["id"] in overdue_ids


def test_get_plan_available_minutes_filters_suggestion(client: TestClient) -> None:
    client.post("/tasks", json={"title": "Too long", "estimated_minutes": 60})
    fits = client.post("/tasks", json={"title": "Fits", "estimated_minutes": 20}).json()

    response = client.get("/plan", params={"available_minutes": 30})

    assert response.status_code == 200
    body = response.json()
    assert body["suggested_task"] is not None
    assert body["suggested_task"]["id"] == fits["id"]
