"""
Setup script for demo mode.

Creates the test user in MongoDB for demo/testing purposes.
"""
import asyncio
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
    
    # Vultr path format
    vultr_resume_path = f"/data/resumes/{user_id}/resume.pdf"
    
    test_user = {
        "email": user_email,
        "first_name": "Automated",
        "last_name": "Tester",
        "phone": "555-010-9988",
        "location": "New York, NY, USA",
        "linkedin_url": "https://linkedin.com/in/dummy-candidate",
        "website_url": "https://dummy-portfolio.com",
        "github_url": "https://github.com/dummy-candidate",
        "resume_path": vultr_resume_path,
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
    print(f"2. Test application: py manual_debug_greenhouse.py")
    print(f"3. Test with submission: py manual_debug_greenhouse.py --submit")
    
    await close_database()


if __name__ == "__main__":
    asyncio.run(main())
