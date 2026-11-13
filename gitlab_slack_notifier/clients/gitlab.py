from __future__ import annotations

import urllib.parse

from ..http import request_json


class GitLab:
    def __init__(self, base_url: str, token: str):
        self.api = base_url.rstrip("/") + "/api/v4"
        self.headers = {"PRIVATE-TOKEN": token}

    # --- low level ---
    def _url(self, path: str, params: dict) -> str:
        params = {k: v for k, v in params.items() if v is not None}
        return f"{self.api}{path}?{urllib.parse.urlencode(params)}"

    def get(self, path: str, **params) -> list | dict:
        """GET with automatic pagination for list endpoints."""
        params.setdefault("per_page", 100)
        out: list = []
        page = 1
        while True:
            data, headers = request_json(self._url(path, {**params, "page": page}), headers=self.headers)
            if not isinstance(data, list):
                return data
            out.extend(data)
            nxt = headers.get("X-Next-Page")
            if not nxt:
                return out
            page = int(nxt)

    @staticmethod
    def project_id(path_or_id: str | int) -> str:
        return urllib.parse.quote(str(path_or_id), safe="")

    # --- domain ---
    def current_user(self) -> dict:
        return self.get("/user")

    def pending_todos(self) -> list[dict]:
        return self.get("/todos", state="pending")

    def project_open_mrs(self, project: str | int, created_after: str | None) -> list[dict]:
        return self.get(
            f"/projects/{self.project_id(project)}/merge_requests",
            state="opened",
            created_after=created_after,
            order_by="created_at",
            sort="asc",
        )

    def my_open_mrs(self) -> list[dict]:
        return self.get("/merge_requests", scope="created_by_me", state="opened")

    def my_mrs_updated_after(self, updated_after: str) -> list[dict]:
        """All your MRs (open, merged, closed) updated recently."""
        return self.get("/merge_requests", scope="created_by_me", state="all", updated_after=updated_after)

    def mrs_to_review(self, username: str) -> list[dict]:
        return self.get("/merge_requests", reviewer_username=username, state="opened", scope="all")

    def latest_mr_notes(self, project_id: int, iid: int, limit: int = 50) -> list[dict]:
        """Most recent notes, oldest first."""
        notes = self.get(
            f"/projects/{project_id}/merge_requests/{iid}/notes",
            sort="desc",
            order_by="created_at",
            per_page=limit,
        )
        return list(reversed(notes))
