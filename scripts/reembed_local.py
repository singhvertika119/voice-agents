"""Fill kb_chunks.embedding_local for every section that does not have it yet (D-122, after migration 0009).

Safe to run again: it only touches sections still missing the new vector, and it never changes the old column.

    uv run python scripts/reembed_local.py
"""
import asyncio
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages/core"))

import httpx  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
from vp_core import embeddings  # noqa: E402

URL, KEY = os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_ROLE_KEY"]
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
PAGE, PARALLEL = 200, 8


async def main() -> None:
    os.environ.setdefault("EMBED_THREADS", str(os.cpu_count() or 4))
    done, t0 = 0, time.perf_counter()
    async with httpx.AsyncClient(base_url=URL, headers=H, timeout=60) as c:
        r = await c.get("/rest/v1/kb_chunks", params={"select": "id", "embedding_local": "is.null", "limit": "1"},
                        headers={"Prefer": "count=exact"})
        if r.status_code == 400 and "embedding_local" in r.text:
            sys.exit("The column is missing: run db/migrations/0009_local_embeddings.sql in the Supabase SQL editor first.")
        r.raise_for_status()
        total = int(r.headers["content-range"].split("/")[-1])
        print(f"{total} sections need the new vector")
        sem = asyncio.Semaphore(PARALLEL)

        async def save(row_id: str, vec: list[float]) -> None:
            async with sem:
                for attempt in range(3):
                    try:
                        u = await c.patch("/rest/v1/kb_chunks", params={"id": f"eq.{row_id}"},
                                          json={"embedding_local": embeddings.to_pg(vec)}, headers={"Prefer": "return=minimal"})
                        u.raise_for_status()
                        return
                    except httpx.HTTPError:
                        if attempt == 2:
                            raise
                        await asyncio.sleep(2 ** attempt)

        while True:
            r = await c.get("/rest/v1/kb_chunks", params={"select": "id,content", "embedding_local": "is.null",
                                                           "order": "id", "limit": str(PAGE)})
            r.raise_for_status()
            rows = r.json()
            if not rows:
                break
            vecs = await embeddings.embed([row["content"] for row in rows])
            await asyncio.gather(*(save(row["id"], v) for row, v in zip(rows, vecs)))
            done += len(rows)
            print(f"  {done}/{total} ({time.perf_counter() - t0:.0f} s)", flush=True)
    print(f"done: {done} sections in {time.perf_counter() - t0:.0f} s")


if __name__ == "__main__":
    asyncio.run(main())
