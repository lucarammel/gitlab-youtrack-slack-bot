from __future__ import annotations

import urllib.parse

from ..http import request_json

ACTIVITY_FIELDS = (
    "id,timestamp,author(login,fullName),category(id),field(presentation),"
    "target(idReadable,summary,text,issue(idReadable,summary)),"
    "added(id,name,login,fullName,text,presentation),removed(name,login,fullName,presentation)"
)


class YouTrack:
    def __init__(self, base_url: str, token: str):
        self.base = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    def get(self, path: str, **params) -> list | dict:
        """GET with $skip/$top pagination for list endpoints."""
        top = 200
        out: list = []
        skip = 0
        while True:
            q = urllib.parse.urlencode({**params, "$top": top, "$skip": skip})
            data, _ = request_json(f"{self.base}/api{path}?{q}", headers=self.headers)
            if not isinstance(data, list):
                return data
            out.extend(data)
            if len(data) < top:
                return out
            skip += top

    def issue_url(self, issue_id: str) -> str:
        return f"{self.base}/issue/{issue_id}"

    # --- domain ---
    def me(self) -> dict:
        return self.get("/users/me", fields="login,fullName")

    def activities(self, start_ms: int, categories: str) -> list[dict]:
        return self.get("/activities", categories=categories, start=start_ms, fields=ACTIVITY_FIELDS)

    def matching_issue_ids(self, query: str, ids: list[str]) -> set[str]:
        """Subset of `ids` matching the YouTrack search `query`."""
        if not ids:
            return set()
        found = self.get("/issues", query=f"({query}) and issue id: {', '.join(ids)}", fields="idReadable")
        return {i["idReadable"] for i in found}

    def search_issues(self, query: str) -> list[dict]:
        return self.get("/issues", query=query, fields="idReadable,summary")
