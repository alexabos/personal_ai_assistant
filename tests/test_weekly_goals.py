"""Tests for the weekly goal API and service layer."""

from datetime import date, timedelta

from fastapi.testclient import TestClient

_REFERENCE_DAY = date(2026, 9, 16)
MONDAY = _REFERENCE_DAY - timedelta(days=_REFERENCE_DAY.weekday())
NEXT_MONDAY = MONDAY + timedelta(days=7)


def test_create_weekly_goal_returns_201(client: TestClient) -> None:
    response = client.post(
        "/weekly-goals",
        json={
            "title": "Improve French speaking",
            "description": "Complete five speaking sessions",
            "week_start": MONDAY.isoformat(),
            "target_minutes": 150,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Improve French speaking"
    assert body["week_start"] == MONDAY.isoformat()
    assert body["status"] == "active"
    assert body["completed_minutes"] == 0


def test_create_weekly_goal_normalizes_week_start_to_monday(client: TestClient) -> None:
    response = client.post(
        "/weekly-goals",
        json={"title": "Read more", "week_start": _REFERENCE_DAY.isoformat()},
    )

    assert response.status_code == 201
    assert response.json()["week_start"] == MONDAY.isoformat()


def test_get_weekly_goal_returns_created_goal(client: TestClient) -> None:
    created = client.post(
        "/weekly-goals", json={"title": "Goal", "week_start": MONDAY.isoformat()}
    ).json()

    response = client.get(f"/weekly-goals/{created['id']}")

    assert response.status_code == 200
    assert response.json()["title"] == "Goal"


def test_get_nonexistent_weekly_goal_returns_404(client: TestClient) -> None:
    response = client.get("/weekly-goals/999")

    assert response.status_code == 404


def test_list_weekly_goals_filters_by_week_start(client: TestClient) -> None:
    week1 = client.post(
        "/weekly-goals", json={"title": "Week 1 goal", "week_start": MONDAY.isoformat()}
    ).json()
    client.post(
        "/weekly-goals", json={"title": "Week 2 goal", "week_start": NEXT_MONDAY.isoformat()}
    )

    response = client.get("/weekly-goals", params={"week_start": MONDAY.isoformat()})

    assert response.status_code == 200
    ids = [goal["id"] for goal in response.json()]
    assert ids == [week1["id"]]


def test_list_weekly_goals_filters_by_status(client: TestClient) -> None:
    active = client.post(
        "/weekly-goals", json={"title": "Active goal", "week_start": MONDAY.isoformat()}
    ).json()
    cancelled = client.post(
        "/weekly-goals", json={"title": "Cancelled goal", "week_start": MONDAY.isoformat()}
    ).json()
    client.post(f"/weekly-goals/{cancelled['id']}/cancel")

    response = client.get("/weekly-goals", params={"status": "active"})

    assert response.status_code == 200
    ids = [goal["id"] for goal in response.json()]
    assert active["id"] in ids
    assert cancelled["id"] not in ids


def test_update_weekly_goal_fields(client: TestClient) -> None:
    created = client.post(
        "/weekly-goals", json={"title": "Goal", "week_start": MONDAY.isoformat()}
    ).json()

    response = client.patch(f"/weekly-goals/{created['id']}", json={"completed_minutes": 60})

    assert response.status_code == 200
    assert response.json()["completed_minutes"] == 60


def test_update_nonexistent_weekly_goal_returns_404(client: TestClient) -> None:
    response = client.patch("/weekly-goals/999", json={"completed_minutes": 10})

    assert response.status_code == 404


def test_complete_weekly_goal(client: TestClient) -> None:
    created = client.post(
        "/weekly-goals", json={"title": "Goal", "week_start": MONDAY.isoformat()}
    ).json()

    response = client.post(f"/weekly-goals/{created['id']}/complete")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_complete_weekly_goal_twice_is_idempotent(client: TestClient) -> None:
    created = client.post(
        "/weekly-goals", json={"title": "Goal", "week_start": MONDAY.isoformat()}
    ).json()
    client.post(f"/weekly-goals/{created['id']}/complete")

    response = client.post(f"/weekly-goals/{created['id']}/complete")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_cancel_weekly_goal(client: TestClient) -> None:
    created = client.post(
        "/weekly-goals", json={"title": "Goal", "week_start": MONDAY.isoformat()}
    ).json()

    response = client.post(f"/weekly-goals/{created['id']}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


def test_cancel_completed_weekly_goal_returns_409(client: TestClient) -> None:
    created = client.post(
        "/weekly-goals", json={"title": "Goal", "week_start": MONDAY.isoformat()}
    ).json()
    client.post(f"/weekly-goals/{created['id']}/complete")

    response = client.post(f"/weekly-goals/{created['id']}/cancel")

    assert response.status_code == 409


def test_complete_cancelled_weekly_goal_returns_409(client: TestClient) -> None:
    created = client.post(
        "/weekly-goals", json={"title": "Goal", "week_start": MONDAY.isoformat()}
    ).json()
    client.post(f"/weekly-goals/{created['id']}/cancel")

    response = client.post(f"/weekly-goals/{created['id']}/complete")

    assert response.status_code == 409


def test_create_weekly_goal_rejects_empty_title(client: TestClient) -> None:
    response = client.post(
        "/weekly-goals", json={"title": "   ", "week_start": MONDAY.isoformat()}
    )

    assert response.status_code == 422


def test_create_weekly_goal_rejects_negative_target_minutes(client: TestClient) -> None:
    response = client.post(
        "/weekly-goals",
        json={"title": "Goal", "week_start": MONDAY.isoformat(), "target_minutes": -10},
    )

    assert response.status_code == 422


def test_update_weekly_goal_rejects_negative_completed_minutes(client: TestClient) -> None:
    created = client.post(
        "/weekly-goals", json={"title": "Goal", "week_start": MONDAY.isoformat()}
    ).json()

    response = client.patch(f"/weekly-goals/{created['id']}", json={"completed_minutes": -5})

    assert response.status_code == 422


def test_weekly_goal_persists_across_requests(client: TestClient) -> None:
    created = client.post(
        "/weekly-goals", json={"title": "Persisted goal", "week_start": MONDAY.isoformat()}
    ).json()

    response = client.get(f"/weekly-goals/{created['id']}")

    assert response.status_code == 200
    assert response.json()["title"] == "Persisted goal"
