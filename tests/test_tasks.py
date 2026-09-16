"""Tests for the task API and service layer."""

from fastapi.testclient import TestClient


def test_create_task_returns_201_and_task(client: TestClient) -> None:
    response = client.post(
        "/tasks",
        json={
            "title": "Study agentic AI",
            "description": "Complete the next course lesson",
            "priority": "high",
            "estimated_minutes": 45,
            "category": "learning",
            "due_date": "2026-09-20",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Study agentic AI"
    assert body["status"] == "pending"
    assert body["priority"] == "high"
    assert body["due_date"] == "2026-09-20"
    assert body["completed_at"] is None
    assert body["id"] is not None


def test_get_task_returns_created_task(client: TestClient) -> None:
    created = client.post("/tasks", json={"title": "Read a book"}).json()

    response = client.get(f"/tasks/{created['id']}")

    assert response.status_code == 200
    assert response.json()["title"] == "Read a book"


def test_get_nonexistent_task_returns_404(client: TestClient) -> None:
    response = client.get("/tasks/999")

    assert response.status_code == 404


def test_list_tasks_excludes_completed_by_default(client: TestClient) -> None:
    pending = client.post("/tasks", json={"title": "Pending task"}).json()
    completed = client.post("/tasks", json={"title": "Completed task"}).json()
    client.post(f"/tasks/{completed['id']}/complete")

    response = client.get("/tasks")

    assert response.status_code == 200
    ids = [task["id"] for task in response.json()]
    assert pending["id"] in ids
    assert completed["id"] not in ids


def test_list_tasks_include_completed_true_shows_completed(client: TestClient) -> None:
    completed = client.post("/tasks", json={"title": "Completed task"}).json()
    client.post(f"/tasks/{completed['id']}/complete")

    response = client.get("/tasks", params={"include_completed": True})

    assert response.status_code == 200
    ids = [task["id"] for task in response.json()]
    assert completed["id"] in ids


def test_list_tasks_filters_by_priority_and_category(client: TestClient) -> None:
    client.post(
        "/tasks", json={"title": "Low priority", "priority": "low", "category": "chores"}
    )
    high = client.post(
        "/tasks", json={"title": "High priority", "priority": "high", "category": "learning"}
    ).json()

    response = client.get("/tasks", params={"priority": "high", "category": "learning"})

    assert response.status_code == 200
    ids = [task["id"] for task in response.json()]
    assert ids == [high["id"]]


def test_update_task_fields(client: TestClient) -> None:
    created = client.post("/tasks", json={"title": "Original title"}).json()

    response = client.patch(
        f"/tasks/{created['id']}", json={"title": "Updated title", "priority": "high"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Updated title"
    assert body["priority"] == "high"


def test_update_nonexistent_task_returns_404(client: TestClient) -> None:
    response = client.patch("/tasks/999", json={"title": "Whatever"})

    assert response.status_code == 404


def test_complete_task_sets_status_and_completed_at(client: TestClient) -> None:
    created = client.post("/tasks", json={"title": "Finish this"}).json()

    response = client.post(f"/tasks/{created['id']}/complete")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["completed_at"] is not None


def test_complete_task_twice_is_idempotent(client: TestClient) -> None:
    created = client.post("/tasks", json={"title": "Finish this"}).json()
    first = client.post(f"/tasks/{created['id']}/complete").json()

    second = client.post(f"/tasks/{created['id']}/complete")

    assert second.status_code == 200
    assert second.json()["completed_at"] == first["completed_at"]


def test_cancel_task_sets_status(client: TestClient) -> None:
    created = client.post("/tasks", json={"title": "Drop this"}).json()

    response = client.post(f"/tasks/{created['id']}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


def test_cancel_completed_task_returns_409(client: TestClient) -> None:
    created = client.post("/tasks", json={"title": "Finish this"}).json()
    client.post(f"/tasks/{created['id']}/complete")

    response = client.post(f"/tasks/{created['id']}/cancel")

    assert response.status_code == 409


def test_complete_cancelled_task_returns_409(client: TestClient) -> None:
    created = client.post("/tasks", json={"title": "Drop this"}).json()
    client.post(f"/tasks/{created['id']}/cancel")

    response = client.post(f"/tasks/{created['id']}/complete")

    assert response.status_code == 409


def test_create_task_rejects_empty_title(client: TestClient) -> None:
    response = client.post("/tasks", json={"title": "   "})

    assert response.status_code == 422


def test_create_task_rejects_negative_estimated_minutes(client: TestClient) -> None:
    response = client.post("/tasks", json={"title": "Task", "estimated_minutes": -5})

    assert response.status_code == 422


def test_create_task_rejects_invalid_priority(client: TestClient) -> None:
    response = client.post("/tasks", json={"title": "Task", "priority": "urgent"})

    assert response.status_code == 422


def test_create_task_rejects_invalid_date_format(client: TestClient) -> None:
    response = client.post("/tasks", json={"title": "Task", "due_date": "not-a-date"})

    assert response.status_code == 422


def test_task_persists_across_requests(client: TestClient) -> None:
    created = client.post(
        "/tasks", json={"title": "Persisted task", "due_date": "2026-10-01"}
    ).json()

    response = client.get(f"/tasks/{created['id']}")

    assert response.status_code == 200
    assert response.json()["due_date"] == "2026-10-01"
