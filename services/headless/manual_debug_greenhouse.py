import argparse
import asyncio
import os
import json
from pathlib import Path
from dotenv import load_dotenv
from app.applying.greenhouse import GreenhouseApplier
from app.db import upsert_user, get_user, close_database

# Load environment variables from project root
project_root = Path(__file__).parent.parent.parent
load_dotenv(project_root / ".env")


async def main():
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Test Greenhouse application automation")
    parser.add_argument("--submit", action="store_true", help="Actually submit the form (default: dry run)")
    parser.add_argument("--keep-open", action="store_true", help="Keep browser open after completion")
    parser.add_argument("--visible", action="store_true", help="Show browser window (not headless)")
    parser.add_argument("--local", action="store_true", help="Use local test data (skip MongoDB)")
    args = parser.parse_args()
    
    # 0. Create local test resume structure matching Vultr path
    # Vultr: /data/resumes/{user_id}/resume.pdf
    # Local: ./data/resumes/{user_id}/resume.pdf (for testing)
    user_email = "thomasariogpt@gmail.com"
    user_id = user_email.replace("@", "_").replace(".", "_")  # thomasariogpt_gmail_com
    
    local_data_dir = Path("./data/resumes") / user_id
    local_data_dir.mkdir(parents=True, exist_ok=True)
    resume_path = local_data_dir / "resume.pdf"
    
    if not resume_path.exists():
        print(f"Creating test resume at {resume_path}...")
        with open(resume_path, "wb") as f:
            # Create a minimal valid PDF
            f.write(b"%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\n2 0 obj\n<<\n/Type /Pages\n/Kids [3 0 R]\n/Count 1\n>>\nendobj\n3 0 obj\n<<\n/Type /Page\n/MediaBox [0 0 595 842]\n>>\nendobj\nxref\n0 4\n0000000000 65535 f\n0000000010 00000 n\n0000000060 00000 n\n0000000111 00000 n\ntrailer\n<<\n/Size 4\n/Root 1 0 R\n>>\nstartxref\n158\n%%EOF")
        print(f"[OK] Created test resume")
    
    # 1. Retrieve test user from MongoDB (or use local test data)
    if args.local:
        print(f"Using local test profile (skipping MongoDB)...")
        user_profile = {
            "email": user_email,
            "first_name": "Test",
            "last_name": "User",
            "phone": "555-123-4567",
            "location": "Toronto, ON",
            "linkedin_url": "https://linkedin.com/in/testuser",
            "portfolio_url": "https://testuser.dev",
            "resume_path": str(resume_path.absolute()),
            "work_authorization": "Authorized to work",
            "years_experience": "3",
            "education": "Bachelor's in Computer Science",
            "skills": ["Python", "JavaScript", "AWS", "Docker"],
        }
    else:
        print(f"Retrieving user: {user_email}...")
        user_profile = await get_user(user_email)

        if not user_profile:
            print(f"Error: User {user_email} not found in database.")
            print("Please run setup_demo.py first to create the test user, or use --local flag.")
            return
    
    # Update user's resume path to local test path
    user_profile["resume_path"] = str(resume_path.absolute())
    print(f"[OK] Using local resume: {user_profile['resume_path']}")

    # 2. Job Description
    job_description = """
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

    # 3. Initialize Applier
    headless = not args.visible  # Default headless unless --visible
    applier = GreenhouseApplier(headless=headless)
    
    url = "https://job-boards.greenhouse.io/atomicmachines/jobs/4092512009"
    
    print(f"\n--- PHASE 1: ANALYSIS ---")
    print(f"Target URL: {url}")
    print(f"Mode: {'Visible' if args.visible else 'Headless'}")
    print("Launching browser to analyze form fields...")
    
    analysis = await applier.analyze_form(
        url, 
        user_profile, 
        job_description=job_description,
        cached_responses={}
    )
    
    if analysis.get("status") == "error":
        print(f"Analysis failed: {analysis.get('message')}")
        return

    print("Analysis complete.")
    fields = analysis.get("fields", [])
    
    # 6. Prompt User for Non-Cached Fields
    print(f"\n--- PHASE 2: REVIEW & INPUT ---")
    print("Reviewing fields. Press Enter to accept Gemini's suggestion.")
    
    for i, field in enumerate(fields):
        print(f"\n[{i+1}/{len(fields)}] Question: {field['label']}")
        print(f"    Type: {field['field_type']}")
        print(f"    Selector: {field.get('selector')}") # Debug info
        
        # Special handling for File fields
        if field['field_type'] == 'file':
            # Check if it's a resume or cover letter based on label or ID
            label_lower = field['label'].lower()
            id_lower = str(field.get('field_id', '')).lower()
            
            if 'resume' in label_lower or 'cv' in label_lower or 'resume' in id_lower:
                field["final_value"] = user_profile["resume_path"]
                # Clear recommended_value to prevent fallback to placeholder if path is empty/invalid (though it shouldn't be)
                field["recommended_value"] = None 
                print(f"    Auto-attached Resume: {user_profile['resume_path']}")
            else:
                # Cover letter or other - leave empty
                print(f"    Skipping optional file: {field['label']} (ID: {field.get('field_id')})")
                field["final_value"] = ""
                field["recommended_value"] = None # CRITICAL: Prevent fallback to "[Resume will be uploaded]" placeholder
            continue

        source = field.get("source")
        # Skip if confident (Profile or Cached)
        if source in ["cached", "profile"]:
            # Set final value automatically
            field["final_value"] = field.get("recommended_value")
            continue
        
        suggestion = field.get("recommended_value")
        print(f"    Gemini Suggestion: \033[92m{suggestion}\033[0m") # Green text
        
        options = field.get("options")
        if options:
            print("    Options:")
            for idx, opt in enumerate(options):
                print(f"      {idx + 1}) {opt}")
        
        # user_input = input("    > ")
        print("    > (Auto-accepting for debug)")
        
        field["final_value"] = suggestion
        print("    Accepted suggestion.")

    # 7. Apply
    print(f"\n--- PHASE 3: APPLICATION ---")
    mode_str = "SUBMITTING" if args.submit else "DRY RUN"
    print(f"Mode: {mode_str}")
    print("Launching browser to fill application...")
    

    async def manual_verification():
        print("\n" + "!" * 50)
        print("ACTION REQUIRED: Email Verification Code")
        print("Please check your email and enter the 8-digit code below:")
        print("!" * 50)
        return await asyncio.get_event_loop().run_in_executor(None, input, "Code: ")

    result = await applier.fill_and_submit(
        url, 
        fields, 
        user_profile=user_profile,
        job_description=job_description,
        expected_fingerprint=None,  # Disable strict check for debug
        submit=args.submit,
        keep_open=args.keep_open,
        verification_callback=manual_verification
    )
    
    print("\nResult:", result)
    
    if args.submit and result.get("status") == "success":
        print(f"\n[OK] Application submitted! Check {user_email} for confirmation.")

    if not args.local:
        await close_database()

if __name__ == "__main__":
    asyncio.run(main())