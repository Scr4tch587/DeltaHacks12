"""
Main scraper orchestration logic - DEMO MODE.

Orchestrates the full pipeline for demo:
1. Hardcode 17 verified demo job URLs
2. Open each page in headless browser
3. Extract visible description and pre-analyze form
4. Generate Gemini embeddings
5. Store in MongoDB with form_schema
"""

import asyncio
import json
import os
import random
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from app.db import ensure_indexes, get_job_count, upsert_job, get_database
from app.rate_limiter import embedding_rate_limiter
from .embeddings import configure_gemini, create_job_embedding_text, generate_embedding

# Hardcoded demo job URLs
DEMO_JOB_URLS = [
    "https://job-boards.greenhouse.io/tlatechinc/jobs/4074977009?gh_src=my.greenhouse.search",
    "https://job-boards.greenhouse.io/roo/jobs/5047408008?gh_src=my.greenhouse.search",
    "https://job-boards.eu.greenhouse.io/lotusworks/jobs/4746237101?gh_src=my.greenhouse.search",
    "https://job-boards.greenhouse.io/redwoodmaterials/jobs/5737879004?gh_jid=5737879004&gh_src=my.greenhouse.search",
    "https://job-boards.greenhouse.io/willowtree/jobs/8364172002?gh_src=my.greenhouse.search",
    "https://job-boards.greenhouse.io/grvty/jobs/4091559009?gh_src=my.greenhouse.search",
    "https://job-boards.greenhouse.io/sirenopt/jobs/4090525009?gh_src=my.greenhouse.search",
    "https://job-boards.greenhouse.io/upwork/jobs/7565868003?gh_src=my.greenhouse.search",
    "https://job-boards.greenhouse.io/cartesiansystems/jobs/4076723009?gh_src=my.greenhouse.search",
    "https://job-boards.greenhouse.io/dynetherapeutics/jobs/5748627004?gh_src=my.greenhouse.search",
    "https://job-boards.greenhouse.io/komodohealth/jobs/8363298002?gh_src=my.greenhouse.search",
    "https://job-boards.greenhouse.io/checkr/jobs/7342475?gh_src=my.greenhouse.search",
    "https://job-boards.greenhouse.io/phizenix/jobs/5058878008?gh_src=my.greenhouse.search",
    "https://job-boards.greenhouse.io/atomicmachines/jobs/4093522009?gh_src=my.greenhouse.search",
    "https://job-boards.greenhouse.io/lexingtonmedical/jobs/5057076008?gh_src=my.greenhouse.search",
    "https://job-boards.greenhouse.io/formativgroup/jobs/4093476009?gh_src=my.greenhouse.search",
    "https://job-boards.greenhouse.io/atomicmachines/jobs/4092512009?gh_src=my.greenhouse.search",
]


def parse_greenhouse_url(url: str) -> tuple[str, int, str] | None:
    """
    Parse a Greenhouse job URL to extract company token and job ID.
    
    Args:
        url: Full Greenhouse job URL
        
    Returns:
        Tuple of (company_token, greenhouse_id, company_name) or None if invalid
    """
    # Pattern: https://job-boards.greenhouse.io/{company}/jobs/{job_id}
    pattern = r'https://job-boards(?:\.eu)?\.greenhouse\.io/([^/]+)/jobs/(\d+)'
    match = re.search(pattern, url)
    
    if match:
        company_token = match.group(1)
        greenhouse_id = int(match.group(2))
        # Use token as name for now (can be improved)
        company_name = company_token.replace("-", " ").title()
        return (company_token, greenhouse_id, company_name)
    
    return None


async def extract_job_details_from_page(url: str, browser) -> dict[str, Any] | None:
    """
    Open the job page in headless browser and extract details.
    
    Returns dict with:
        - title
        - description_text (visible page content)
        - form_schema (pre-analyzed form fields)
    """
    try:
        from app.applying.greenhouse import GreenhouseApplier, compute_form_fingerprint
        
        page = await browser.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)  # Let dynamic content load
        
        # Extract title
        title = ""
        try:
            title_elem = await page.query_selector("h1.app-title, .job-title, h1")
            if title_elem:
                title = await title_elem.inner_text()
        except:
            pass
        
        # Extract visible description text
        description_text = ""
        try:
            # Try to find the job description container
            desc_selectors = [
                "#content",
                ".content",
                "#job-content",
                ".job-description",
                "[data-qa='job-description']"
            ]
            
            for selector in desc_selectors:
                elem = await page.query_selector(selector)
                if elem:
                    description_text = await elem.inner_text()
                    if description_text and len(description_text) > 100:
                        break
            
            # Fallback: get all visible text
            if not description_text or len(description_text) < 100:
                description_text = await page.inner_text("body")
        except Exception as e:
            print(f"   Warning: Could not extract description: {e}")
        
        # Pre-analyze form fields using GreenhouseApplier
        applier = GreenhouseApplier(headless=True)
        form_fields = await applier._extract_form_fields(page)
        
        # Compute fingerprint
        fingerprint = compute_form_fingerprint(form_fields)
        
        form_schema = {
            "fields": form_fields,
            "fingerprint": fingerprint,
            "analyzed_at": datetime.utcnow()
        }
        
        await page.close()
        
        return {
            "title": title.strip(),
            "description_text": description_text.strip(),
            "form_schema": form_schema
        }
        
    except Exception as e:
        print(f"   Error extracting from page: {e}")
        return None


async def scrape_demo_job(url: str, browser) -> bool:
    """
    Scrape a single demo job URL.
    
    Returns:
        True if successfully scraped and stored
    """
    parsed = parse_greenhouse_url(url)
    if not parsed:
        print(f"   ✗ Invalid URL format: {url}")
        return False
    
    company_token, greenhouse_id, company_name = parsed
    print(f"[{company_name}] Processing job {greenhouse_id}...")
    
    # Check if job already has complete data
    db = await get_database()
    existing = await db.jobs.find_one({"greenhouse_id": greenhouse_id})
    
    if existing and existing.get("form_schema") and existing.get("embedding"):
        print(f"   ✓ Already complete, skipping")
        return True
    
    # Extract details from page
    print(f"   Opening page in headless browser...")
    page_data = await extract_job_details_from_page(url, browser)
    
    if not page_data:
        print(f"   ✗ Failed to extract page data")
        return False
    
    # Build job document
    doc = {
        "greenhouse_id": greenhouse_id,
        "company_token": company_token,
        "company_name": company_name,
        "title": page_data["title"],
        "location": None,  # Could be extracted if needed
        "department": None,
        "description_text": page_data["description_text"],
        "absolute_url": url,
        "updated_at": datetime.utcnow(),
        "active": True,
        "form_schema": page_data["form_schema"]
    }
    
    # Generate embedding from visible description
    print(f"   Generating embedding...")
    embedding_text = create_job_embedding_text(doc)
    
    await embedding_rate_limiter.acquire()
    doc["embedding"] = await generate_embedding(embedding_text)
    
    # Store in MongoDB
    print(f"   Storing in database...")
    success = await upsert_job(doc)
    
    if success:
        print(f"   ✓ Stored: {page_data['title']}")
    else:
        print(f"   ✗ Failed to store")
    
    return success


async def run_scraper() -> dict[str, Any]:
    """
    Run the demo scraping pipeline.
    
    Returns:
        Summary dict with jobs_stored, total_jobs
    """
    print("=" * 60)
    print("Starting DEMO Job Scraper")
    print("=" * 60)

    # Configure Gemini API
    print("Configuring Gemini API...")
    try:
        configure_gemini()
        print("✓ Gemini API configured successfully")
    except ValueError as e:
        print(f"✗ Failed to configure Gemini: {e}")
        return {"error": str(e)}

    # Ensure MongoDB indexes
    print("Ensuring MongoDB indexes...")
    try:
        await ensure_indexes()
        print("✓ MongoDB indexes ready")
    except Exception as e:
        print(f"✗ Failed to setup MongoDB: {e}")
        return {"error": str(e)}

    print(f"✓ Loaded {len(DEMO_JOB_URLS)} demo URLs")
    print()

    # Start browser
    jobs_stored = 0
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        
        # Concurrency control for scraping
        # User requested 10 concurrent tabs (Vultr server has 24GB RAM)
        sem = asyncio.Semaphore(10)
        tasks = []

        async def scrape_worker(idx, url):
            async with sem:
                # Add a small random delay to prevent thundering herd on browser launch
                await asyncio.sleep(random.uniform(0.1, 1.0))
                print(f"--- Starting Job {idx}/{len(DEMO_JOB_URLS)} ---")
                try:
                    success = await scrape_demo_job(url, browser)
                    return 1 if success else 0
                except Exception as e:
                    print(f"✗ Error scraping {url}: {e}")
                    import traceback
                    traceback.print_exc()
                    return 0

        print(f"Launching {len(DEMO_JOB_URLS)} jobs with concurrency=10...")
        for idx, url in enumerate(DEMO_JOB_URLS, 1):
            tasks.append(asyncio.create_task(scrape_worker(idx, url)))
        
        results = await asyncio.gather(*tasks)
        jobs_stored = sum(results)
        
        await browser.close()

    # Get final count from database
    print("\nFetching final job count from database...")
    final_count = await get_job_count()

    print("\n" + "=" * 60)
    print("SCRAPING COMPLETE!")
    print("=" * 60)
    print(f"  Jobs processed: {len(DEMO_JOB_URLS)}")
    print(f"  Jobs stored this run: {jobs_stored}")
    print(f"  Total jobs in database: {final_count}")
    print("=" * 60)

    return {
        "jobs_stored": jobs_stored,
        "total_jobs_in_db": final_count,
    }


if __name__ == "__main__":
    # Allow running directly for testing
    asyncio.run(run_scraper())
