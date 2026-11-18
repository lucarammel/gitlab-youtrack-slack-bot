"""In-memory stand-ins for the API clients."""

from __future__ import annotations

from gitlab_slack_notifier.config import Config

ME = {"id": 1, "username": "me", "name": "Lucas Pereira"}


def make_config(**overrides) -> Config:
    return Config(gitlab_url="https://gitlab.example.com", **overrides)


def mr(id: int, iid: int, title: str = "Some MR", author: dict | None = None, **extra) -> dict:
    return {
        "id": id,
        "iid": iid,
        "project_id": 10,
        "title": title,
        "web_url": f"https://gitlab.example.com/p/-/merge_requests/{iid}",
        "references": {"full": f"group/p!{iid}"},
        "author": author or {"id": 2, "username": "alice", "name": "Alice"},
        "created_at": "2026-11-10T09:00:00Z",
        **extra,
    }


class FakeGitLab:
    def __init__(self):
        self.todos: list[dict] = []
        self.project_mrs: dict[str, list[dict]] = {}
        self.my_mrs: list[dict] = []
        self.merged_mrs: list[dict] = []
        self.review_mrs: list[dict] = []
        self.reviewed_mrs: list[dict] = []
        self.discussions: dict[int, list[dict]] = {}
        self.notes: dict[int, list[dict]] = {}
        self.pipelines: dict[int, dict] = {}
        self.events: list[dict] = []
        self.recap_merged: list[dict] = []
        self.fail = False

    def _check(self):
        if self.fail:
            from gitlab_slack_notifier.http import ApiError

            raise ApiError("gitlab.example.com: <urlopen error timed out>")

    def current_user(self):
        self._check()
        return ME

    def pending_todos(self):
        self._check()
        return self.todos

    def project_open_mrs(self, project, created_after):
        return self.project_mrs.get(project, [])

    def my_open_mrs(self):
        return self.my_mrs

    def my_mrs_updated_after(self, updated_after):
        return self.my_mrs + self.merged_mrs

    def mrs_to_review(self, username):
        return self.review_mrs

    def reviewed_mrs_updated_after(self, username, updated_after):
        return self.reviewed_mrs

    def mr_discussions(self, project_id, iid):
        return self.discussions.get(iid, [])

    def latest_mr_notes(self, project_id, iid, limit=50):
        return self.notes.get(iid, [])

    def latest_mr_pipeline(self, project_id, iid):
        return self.pipelines.get(iid)

    def user_events(self, user_id, after, before):
        return self.events

    def my_merged_mrs(self, updated_after):
        return self.recap_merged

    def project(self, project_id):
        return {"id": project_id, "name": f"proj{project_id}", "path": f"proj{project_id}",
                "web_url": f"https://gitlab.example.com/g/proj{project_id}"}


class FakeSlack:
    def __init__(self, fail_after: int | None = None):
        self.sent: list[str] = []
        self.fail_after = fail_after

    def post(self, text: str) -> None:
        if self.fail_after is not None and len(self.sent) >= self.fail_after:
            from gitlab_slack_notifier.http import ApiError

            raise ApiError("slack down")
        self.sent.append(text)
