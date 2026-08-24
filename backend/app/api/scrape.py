import asyncio

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import verify_scrapers_api_key
from app.services import scraper_import
from app.services.scraper_runner import (
    cleanup_scraped_csvs,
    get_active_job_id,
    get_job,
    get_last_run,
    start_scrape_job,
)


router = APIRouter(prefix="/api/v1/scrape", dependencies=[Depends(verify_scrapers_api_key)], tags=["scrape"])


@router.post("/run", status_code=202)
async def run_scrape():
    if get_active_job_id():
        raise HTTPException(status_code=409, detail="Scrape já esta em andamento")
    job_id = await start_scrape_job()
    if not job_id:
        raise HTTPException(status_code=409, detail="Scrape já em andamento")
    return {"job_id": job_id}


@router.get("/status/{job_id}")
async def scrape_status(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job não encontrado")
    return {
        "job_id": job.job_id,
        "status": job.status,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "report": job.report,
        "error": job.error,
    }


@router.get("/last-run")
async def scrape_last_run():
    doc = await get_last_run()
    return {"finished_at": (doc or {}).get("finished_at")}


@router.post("/import")
async def import_scraped():
    if get_active_job_id():
        raise HTTPException(status_code=409, detail="Coleta em andamento; tente importar depois")
    result = await asyncio.to_thread(scraper_import.import_scraped_csvs)
    _ = await asyncio.to_thread(cleanup_scraped_csvs)
    return result
