import asyncio
import os
import json
import argparse
from dotenv import load_dotenv
from app.applying.greenhouse import GreenhouseApplier
from app.db import upsert_user, get_user, close_database
from playwright.async_api import async_playwright

# Load environment variables from .env
load_dotenv()

URLS = [
    
]

RESULTS_FILE = "manual_test_results.json"
DOWNLOAD_DIR = "test_the_main_ones"

async def download_page_content(url, output_path):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url)
        # Wait for form to load
        try:
            await page.wait_for_selector("form", timeout=10000)
        except:
            pass
        content = await page.content()
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)
        await browser.close()

async def main():
    parser = argparse.ArgumentParser(description="Test Greenhouse application filling.")
    parser.add_argument("--just_download", action="store_true", help="Download HTML and plan only, do not fill interactively.")
    args = parser.parse_args()

    # 0. Ensure Fixtures and Directories Exist
    fixtures_dir = os.path.join(os.getcwd(), "tests", "fixtures")
    os.makedirs(fixtures_dir, exist_ok=True)
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    resume_path = os.path.join(fixtures_dir, "dummy_resume.pdf")
    
    if not os.path.exists(resume_path):
        print(f"Creating dummy resume at {resume_path}...")
        with open(resume_path, "wb") as f:
            f.write(b"%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\n2 0 obj\n<<\n/Type /Pages\n/Kids [3 0 R]\n/Count 1\n>>\nendobj\n3 0 obj\n<<\n/Type /Page\n/MediaBox [0 0 595 842]\n>>\nendobj\nxref\n0 4\n0000000000 65535 f\n0000000010 00000 n\n0000000060 00000 n\n0000000111 00000 n\ntrailer\n<<\n/Size 4\n/Root 1 0 R\n>>\nstartxref\n158\n%%EOF")

    # 1. Setup Test Data (Fixture)
    test_user = {
        "email": "alex.smith.temp@example.com",
        "first_name": "Alex",
        "last_name": "Smith",
        "phone": "555-010-9988",
        "location": "New York, NY, USA",
        "linkedin_url": "https://linkedin.com/in/dummy-candidate",
        "website_url": "https://dummy-portfolio.com",
        "github_url": "https://github.com/dummy-candidate",
        "resume_path": resume_path,
        "education": [
            {
                "degree": "Bachelor of Science in Computer Science",
                "school": "University of Technology",
                "year": "2020"
            }
        ],
        "experience": [
             {
                 "company": "TechCorp",
                 "role": "Senior Software Engineer",
                 "duration": "2020 - Present",
                 "description": "Developed scalable backend services using Python and FastAPI. Managed AWS infrastructure."
             }
        ],
        "skills": ["Python", "JavaScript", "TypeScript", "AWS", "Docker", "Kubernetes", "React", "MongoDB"],
        "race": "Prefer not to answer",
        "gender": "Prefer not to answer",
        "veteran_status": "I am not a protected veteran",
        "disability": "I do not have a disability",
        "authorization": "I am authorized to work in this country for any employer",
        "sponsorship": "I do not require sponsorship",
        "salary": "Negotiable based on total compensation"
    }
    
    # 2. Upsert User to DB
    print("Upserting test user to MongoDB...")
    await upsert_user(test_user)
    
    # 3. Retrieve User
    user_profile = await get_user(test_user["email"])
    if not user_profile:
        print("Error: Could not retrieve user.")
        return

    # 4. Job Description (Generic Placeholder)
    job_description = ""
    """
    Software Engineer
    
    We are looking for a Software Engineer to join our team.
    
    Requirements:
    - 3+ years of experience with Python and AWS.
    - Experience with Docker and CI/CD.
    - Strong problem solving skills.
    
    Benefits:
    - Competitive salary
    - Remote work
    """

    # Initialize results list
    test_results = []
    if os.path.exists(RESULTS_FILE) and not args.just_download:
        try:
            with open(RESULTS_FILE, "r") as f:
                test_results = json.load(f)
        except:
            pass
    
    processed_urls = {res["url"] for res in test_results} if not args.just_download else set()

    # 5. Initialize Applier
    # Use headless=True if just downloading to be faster/less intrusive
    applier = GreenhouseApplier(headless=args.just_download)
    
    try:
        for idx, url in enumerate(URLS):
            if url in processed_urls:
                print(f"Skipping already processed URL [{idx+1}/{len(URLS)}]: {url}")
                continue

            print(f"\n==================================================")
            print(f"TESTING URL [{idx+1}/{len(URLS)}]: {url}")
            print(f"==================================================")
            
            try:
                # Determine filenames
                # Sanitize URL for filename
                safe_name = "".join([c if c.isalnum() else "_" for c in url.split("?")[0][-20:]])
                html_path = os.path.join(DOWNLOAD_DIR, f"job_{idx+1}_{safe_name}.html")
                json_path = os.path.join(DOWNLOAD_DIR, f"plan_{idx+1}_{safe_name}.json")

                if args.just_download:
                    print(f"Downloading content to {html_path}...")
                    # Download HTML independently to capture raw state
                    await download_page_content(url, html_path)

                print(f"--- PHASE 1: ANALYSIS ---")
                analysis = await applier.analyze_form(
                    url, 
                    user_profile, 
                    job_description=job_description,
                    cached_responses={}
                )
                
                if analysis.get("status") == "error":
                    print(f"Analysis failed: {analysis.get('message')}")
                    # Record failure
                    if not args.just_download:
                        test_results.append({
                            "url": url,
                            "success": False,
                            "reason": f"Analysis failed: {analysis.get('message')}"
                        })
                    continue

                fields = analysis.get("fields", [])
                
                # Auto-accept all recommendations for speed
                print(f"--- PHASE 2: AUTO-ACCEPTING SUGGESTIONS ---")
                for field in fields:
                    # File handling
                    if field['field_type'] == 'file':
                        label_lower = field['label'].lower()
                        id_lower = str(field.get('field_id', '')).lower()
                        if 'resume' in label_lower or 'cv' in label_lower or 'resume' in id_lower:
                            field["final_value"] = test_user["resume_path"]
                            field["recommended_value"] = None 
                        else:
                            field["final_value"] = ""
                            field["recommended_value"] = None
                        continue

                    # Standard fields
                    source = field.get("source")
                    if source in ["cached", "profile"]:
                        field["final_value"] = field.get("recommended_value")
                        continue
                    
                    suggestion = field.get("recommended_value")
                    field["final_value"] = suggestion

                if args.just_download:
                    print(f"Saving analysis plan to {json_path}...")
                    with open(json_path, "w", encoding="utf-8") as f:
                        json.dump(analysis, f, indent=2, default=str)
                    print("Skipping fill phase (just_download mode).")
                    continue

                print(f"--- PHASE 3: FILLING FORM ---")
                # We use a custom call here that waits for user input BEFORE closing
                
                failed_html_path = os.path.join(DOWNLOAD_DIR, f"failed_job_{idx+1}_{safe_name}.html")
                
                result = await applier.fill_and_submit(
                    url, 
                    fields, 
                    user_profile=user_profile,
                    job_description=job_description,
                    expected_fingerprint=None,
                    submit=False,
                    keep_open=True,
                    output_path=failed_html_path
                )
                
                print("Form filled. Please check the browser window.")
                user_response = input("Did all fields fill correctly? (y/n): ").strip().lower()
                
                success = user_response == 'y'
                notes = ""
                if not success:
                    notes = input("What was wrong? (optional): ").strip()
                else:
                    # If successful, remove the debug HTML
                    if os.path.exists(failed_html_path):
                        try:
                            os.remove(failed_html_path)
                        except:
                            pass
                
                test_results.append({
                    "url": url,
                    "success": success,
                    "notes": notes
                })

                # Save progress immediately
                with open(RESULTS_FILE, "w") as f:
                    json.dump(test_results, f, indent=2)

                print("Moving to next URL...")
                
            except Exception as e:
                print(f"Error processing {url}: {e}")
                if not args.just_download:
                    test_results.append({
                        "url": url,
                        "success": False,
                        "reason": str(e)
                    })

    finally:
        await close_database()
        if not args.just_download:
            print(f"\nTest complete. Results saved to {RESULTS_FILE}")
        else:
            print(f"\nDownload complete. Files saved to {DOWNLOAD_DIR}/")

if __name__ == "__main__":
    asyncio.run(main())