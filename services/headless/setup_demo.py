"""
Setup script for demo mode.

Creates the test user in MongoDB for demo/testing purposes.
"""
import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from app.db import upsert_user, get_user, close_database

# Load environment variables from project root
project_root = Path(__file__).parent.parent.parent
load_dotenv(project_root / ".env")


async def main():
    print("=" * 60)
    print("DEMO SETUP")
    print("=" * 60)
    
    # Define test user matching the user from the request
    user_email = "thomasariogpt@gmail.com"
    user_id = user_email.replace("@", "_").replace(".", "_")
    
    # Determined path based on OS
    if os.name == 'nt':
        # Windows (Local Dev)
        base_dir = Path(__file__).parent / "data" / "resumes" / user_id
        resume_path = base_dir / "resume.pdf"
        
        # Ensure directory and dummy file exist
        print(f"\n[Windows] Configuring local resume path: {base_dir}")
        base_dir.mkdir(parents=True, exist_ok=True)
        
        if not resume_path.exists():
            print("   Creating dummy resume.pdf...")
            with open(resume_path, "wb") as f:
                f.write(b"%PDF-1.4\n%Dummy Resume PDF Content")
        
        final_path = str(resume_path)
    else:
        # Linux (Vultr Production)
        final_path = f"/data/resumes/{user_id}/resume.pdf"
        print(f"\n[Linux] Using Vultr resume path: {final_path}")
    
    test_user = {
        "email": user_email,
        "first_name": "Charlieeee",
        "last_name": "Kirkeee",
        "phone": "647-555-0123",
        "location": "Toronto, ON, Canada",
        "linkedin_url": "https://linkedin.com/in/charliekirrrk",
        "website_url": "https://kirkinator.dev",
        "github_url": "https://github.com/charlseeee",
        "resume_path": final_path,
        "education": [
            {
                "degree": "Bachelor of Science in Computer Science",
                "school": "University of Waterloo",
                "year": "2023"
            }
        ],
        "experience": [
            {
                "company": "Shopify",
                "role": "Software Developer Intern",
                "duration": "May 2022 - Aug 2022",
                "description": "Built internal tools and APIs using Ruby on Rails and React. Improved checkout performance by 15%."
            }
        ],
        "skills": [
            "Python", "JavaScript", "TypeScript", "AWS", 
            "Docker", "Kubernetes", "React", "MongoDB"
        ],
        "race": "Prefer not to answer",
        "gender": "Prefer not to answer",
        "veteran_status": "I am not a protected veteran",
        "disability": "I do not have a disability",
        "authorization": "I am authorized to work in this country for any employer",
        "sponsorship": "I do not require sponsorship"
    }
    
    print(f"\n1. Upserting test user: {user_email}")
    success = await upsert_user(test_user)
    
    if success:
        print(f"   ✓ User created/updated successfully")
    else:
        print(f"   ✗ Failed to create user")
        return
    
    # Verify
    user = await get_user(user_email)
    if user:
        print(f"   ✓ Verified user exists in database")
        print(f"   Resume path: {user.get('resume_path')}")
    
    print("\n" + "=" * 60)
    print("SETUP COMPLETE")
    print("=" * 60)
    print(f"\nNext steps:")
    print(f"1. Run scraper: py -c \"import asyncio; from app.fetching.scraper import run_scraper; asyncio.run(run_scraper())\"")
    print(f"2. Restart API (if running) so it picks up the DB change")
    print(f"3. Run integration test: py test_integration.py")
    
    await close_database()


if __name__ == "__main__":
    asyncio.run(main())
