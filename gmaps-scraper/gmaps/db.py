from datetime import datetime, timezone

from supabase import Client, create_client

from gmaps.config import Config

UPSERT_CHUNK = 200
PAGE = 1000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Db:
    def __init__(self, client: Client):
        self.c = client

    @classmethod
    def connect(cls, cfg: Config) -> "Db":
        return cls(create_client(cfg.supabase_url, cfg.supabase_key))

    # settings
    def get_setting(self, key: str, default=None):
        rows = self.c.table("settings").select("value").eq("key", key).execute().data
        return rows[0]["value"] if rows else default

    # runs
    def reset_stale(self) -> int:
        reset = (
            self.c.table("search_queue")
            .update({"status": "pending", "run_id": None, "started_at": None})
            .eq("status", "running")
            .execute()
            .data
        )
        self.c.table("runs").update(
            {"status": "failed", "finished_at": _now(), "notes": "interrupted"}
        ).eq("status", "running").execute()
        return len(reset)

    def create_run(self, trigger: str, limit: int | None) -> int:
        row = self.c.table("runs").insert({"trigger": trigger, "place_limit": limit}).execute().data[0]
        return row["id"]

    def finish_run(self, run_id: int, status: str, stats: dict, notes: str | None) -> None:
        self.c.table("runs").update(
            {**stats, "status": status, "notes": notes, "finished_at": _now()}
        ).eq("id", run_id).execute()

    # searches
    def claim_next_search(self, run_id: int) -> dict | None:
        rows = self.c.rpc("claim_next_search", {"p_run_id": run_id}).execute().data
        return rows[0] if rows else None

    def finish_search(self, search_id: int, status: str, found: int, new: int, error: str | None = None) -> None:
        self.c.table("search_queue").update(
            {"status": status, "found_count": found, "new_count": new, "error": error, "finished_at": _now()}
        ).eq("id", search_id).execute()

    def existing_searches(self, client: str, queries: list[str]) -> list[dict]:
        out: list[dict] = []
        for i in range(0, len(queries), 100):
            out += (
                self.c.table("search_queue")
                .select("query,status,finished_at")
                .eq("client", client)
                .in_("query", queries[i : i + 100])
                .execute()
                .data
            )
        return out

    def insert_searches(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        return len(self.c.table("search_queue").insert(rows).execute().data)

    # places
    def known_place_ids(self, place_ids: list[str]) -> set[str]:
        known: set[str] = set()
        for i in range(0, len(place_ids), 100):
            rows = (
                self.c.table("places").select("place_id").in_("place_id", place_ids[i : i + 100]).execute().data
            )
            known.update(r["place_id"] for r in rows)
        return known

    def upsert_places(self, places: list[dict], client: str, search_id: int) -> int:
        new = 0
        for i in range(0, len(places), UPSERT_CHUNK):
            rows = self.c.rpc(
                "upsert_places",
                {"p_places": places[i : i + UPSERT_CHUNK], "p_client": client, "p_search_id": search_id},
            ).execute().data
            new += sum(1 for r in rows if r["out_is_new"])
        return new

    # exports
    def fetch_leads(self, client, since, keyword, include_no_email, new_only) -> list[dict]:
        params = {
            "p_client": client,
            "p_since": since,
            "p_keyword": keyword,
            "p_include_no_email": include_no_email,
            "p_new_only": new_only,
        }
        out: list[dict] = []
        offset = 0
        while True:
            page = self.c.rpc("leads_for_export", params).range(offset, offset + PAGE - 1).execute().data
            out += page
            if len(page) < PAGE:
                return out
            offset += PAGE

    def record_export(self, client: str, filters: dict, file_name: str, place_ids: list[str]) -> int:
        row = self.c.table("exports").insert(
            {"client": client, "filters": filters, "row_count": len(place_ids), "file_name": file_name}
        ).execute().data[0]
        for i in range(0, len(place_ids), 500):
            self.c.table("export_items").insert(
                [{"export_id": row["id"], "place_id": pid} for pid in place_ids[i : i + 500]]
            ).execute()
        return row["id"]

    # status
    def status_summary(self) -> dict:
        queue = {}
        for status in ("pending", "running", "done", "failed"):
            res = self.c.table("search_queue").select("id", count="exact").eq("status", status).limit(1).execute()
            queue[status] = res.count or 0
        runs = self.c.table("runs").select("*").order("id", desc=True).limit(1).execute().data
        return {"queue": queue, "last_run": runs[0] if runs else None}
