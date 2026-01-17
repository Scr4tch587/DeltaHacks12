import argparse
import asyncio
import os
import json
import re
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright
from app.applying.greenhouse import GreenhouseApplier
# LOCAL MODE: Database imports commented out
# from app.db import upsert_user, get_user, close_database

# Load environment variables from project root
project_root = Path(__file__).parent.parent.parent
load_dotenv(project_root / ".env")

# Path to store Gmail browser session (so you only login once)
GMAIL_SESSION_DIR = Path(__file__).parent / ".gmail_session"


async def fetch_2fa_from_gmail(email_address: str, max_wait_seconds: int = 120) -> str | None:
    """
    Open Gmail in browser, find the Greenhouse verification email, and extract the 8-digit code.

    Args:
        email_address: Gmail address to check
        max_wait_seconds: How long to wait/retry for the email

    Returns:
        8-digit verification code or None if not found
    """
    print("\n" + "=" * 60)
    print("FETCHING 2FA CODE FROM GMAIL (Browser)")
    print("=" * 60)
    print(f"Email: {email_address}")
    print(f"Will wait up to {max_wait_seconds}s for the verification email...")

    # Create session directory if it doesn't exist
    GMAIL_SESSION_DIR.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        # Use installed Chrome with persistent profile to avoid "browser not secure" error
        # channel="chrome" uses your installed Chrome instead of Playwright's Chromium
        browser = await p.chromium.launch_persistent_context(
            user_data_dir=str(GMAIL_SESSION_DIR),
            headless=False,  # Must be visible for login
            channel="chrome",  # Use installed Chrome to avoid Google blocking
            args=[
                '--start-maximized',
                '--disable-blink-features=AutomationControlled',  # Hide automation
            ]
        )

        page = await browser.new_page()

        try:
            # Go to Gmail
            print("\n[GMAIL] Opening Gmail...")
            await page.goto("https://mail.google.com/mail/u/0/#inbox")

            # Wait for Gmail to load (either inbox or login page)
            await page.wait_for_timeout(3000)

            # Check if we need to login
            current_url = page.url
            if "accounts.google.com" in current_url or "signin" in current_url:
                print("\n[GMAIL] Login required!")
                print("Please log in to Gmail in the browser window...")
                print("(Your session will be saved for future runs)")

                # Wait for user to complete login (up to 5 minutes)
                for _ in range(60):
                    await page.wait_for_timeout(5000)
                    if "mail.google.com" in page.url and "inbox" in page.url.lower():
                        print("[GMAIL] Login successful!")
                        break
                else:
                    print("[GMAIL] Login timeout - please try again")
                    return None

            # Now search for Greenhouse emails
            start_time = asyncio.get_event_loop().time()
            attempt = 0

            while asyncio.get_event_loop().time() - start_time < max_wait_seconds:
                attempt += 1
                print(f"\n[GMAIL] Attempt {attempt}: Searching for Greenhouse verification email...")

                # Click the search box and search for Greenhouse
                search_box = page.locator("input[aria-label='Search mail']")
                if await search_box.count() > 0:
                    await search_box.click()
                    await search_box.fill("")
                    await page.wait_for_timeout(300)
                    await search_box.fill("from:Greenhouse")
                    await page.keyboard.press("Enter")
                    await page.wait_for_timeout(2000)

                # Look for email rows in the results
                # Try to find the most recent email (first row)
                email_rows = page.locator("tr.zA")  # Gmail email row class
                row_count = await email_rows.count()

                if row_count > 0:
                    print(f"[GMAIL] Found {row_count} matching email(s)")

                    # Extract subject/snippet text from email rows directly (no need to open)
                    print("[GMAIL] Reading subject lines and snippets from email list...")

                    email_previews = await page.evaluate("""
                        () => {
                            const results = [];
                            const rows = document.querySelectorAll('tr.zA');
                            for (let i = 0; i < Math.min(rows.length, 10); i++) {
                                const row = rows[i];
                                // Get subject (span.bog or span.bqe)
                                const subjectEl = row.querySelector('span.bog, span.bqe, .y6 span');
                                // Get snippet/preview (span.y2)
                                const snippetEl = row.querySelector('span.y2, .y2');
                                // Get full row text as backup
                                const fullText = row.innerText;

                                results.push({
                                    subject: subjectEl ? subjectEl.innerText : '',
                                    snippet: snippetEl ? snippetEl.innerText : '',
                                    fullText: fullText
                                });
                            }
                            return results;
                        }
                    """)

                    # Check each email preview for 8-digit code
                    found_security_email = False
                    for i, preview in enumerate(email_previews):
                        subject = preview.get('subject', '')
                        snippet = preview.get('snippet', '')
                        full_text = preview.get('fullText', '')

                        print(f"\n[GMAIL] Email {i+1}:")
                        print(f"  Subject: {subject[:80]}")
                        print(f"  Snippet: {snippet[:80]}")

                        # Combine all text and search for code
                        all_text = f"{subject} {snippet} {full_text}"

                        # Look for 8-digit verification code
                        code_match = re.search(r'(?:application:\s*|code:\s*)([A-Za-z0-9]{8})\b', all_text)
                        if code_match:
                            code = code_match.group(1)
                            print(f"\n[GMAIL] Found verification code in email {i+1}: {code}")
                            print("=" * 60)
                            return code

                        # Check if this is a security code email (need to open it)
                        if 'security code' in subject.lower() or 'verification' in subject.lower():
                            found_security_email = True
                            print(f"\n[GMAIL] Found security code email at position {i+1}! Opening it...")

                            # Use Gmail keyboard shortcuts to navigate and open
                            # First click on the page to ensure focus, then use 'j' to go down, 'o' to open
                            try:
                                # Click on the main content area to focus Gmail
                                await page.click("div[role='main']", timeout=5000)
                                await page.wait_for_timeout(500)

                                # Use keyboard: 'j' moves to next email, press it i times to get to our email
                                # Then 'o' or Enter opens it
                                print(f"[GMAIL] Using keyboard navigation (pressing 'j' {i} times, then Enter)...")

                                for _ in range(i):
                                    await page.keyboard.press("j")
                                    await page.wait_for_timeout(200)

                                # Press Enter or 'o' to open the email
                                await page.keyboard.press("Enter")
                                await page.wait_for_timeout(3000)

                            except Exception as e:
                                print(f"[GMAIL] Keyboard method 1 failed: {e}")
                                # Fallback: Try clicking directly via JavaScript dispatch
                                print("[GMAIL] Trying JavaScript click dispatch...")
                                try:
                                    await page.evaluate(f"""
                                        () => {{
                                            const rows = document.querySelectorAll('tr.zA');
                                            if (rows[{i}]) {{
                                                // Try multiple click methods
                                                const row = rows[{i}];

                                                // Method 1: Focus and dispatch keyboard event
                                                row.focus();
                                                row.dispatchEvent(new KeyboardEvent('keydown', {{key: 'Enter', bubbles: true}}));

                                                // Method 2: Find clickable child and click it
                                                const clickable = row.querySelector('td.xY') || row.querySelector('span.bog') || row.querySelector('span.y2');
                                                if (clickable) {{
                                                    clickable.click();
                                                }}
                                            }}
                                        }}
                                    """)
                                    await page.wait_for_timeout(3000)
                                except Exception as e2:
                                    print(f"[GMAIL] JS click also failed: {e2}")

                            # Now try to extract the email body
                            body_content = await page.evaluate("""
                                () => {
                                    // Try multiple selectors for email body
                                    const selectors = [
                                        'div.a3s.aiL',
                                        'div.a3s',
                                        '.ii.gt',
                                        '[data-message-id]',
                                        '.adn.ads',
                                        '.nH.hx',  // Email view container
                                        '.AO'      // Main content area
                                    ];
                                    for (const sel of selectors) {
                                        const el = document.querySelector(sel);
                                        if (el && el.innerText.length > 100) {
                                            return el.innerText;
                                        }
                                    }
                                    // Fallback: get all visible text
                                    return document.body.innerText;
                                }
                            """)

                            if body_content:
                                print(f"[GMAIL] Page content extracted ({len(body_content)} chars)")
                                # Look for 8-digit code
                                code_match = re.search(r'(?:application:\s*|code:\s*)([A-Za-z0-9]{8})\b', body_content)
                                if code_match:
                                    code = code_match.group(1)
                                    print(f"\n[GMAIL] Found verification code: {code}")
                                    print("=" * 60)
                                    return code
                                else:
                                    # Show more of the content for debugging
                                    print(f"[GMAIL] No 8-digit code found. Content preview:")
                                    print(body_content[:500])

                            break  # Don't check other emails if we found the security email

                    if not found_security_email:
                        print("[GMAIL] No 8-digit code found in any email preview")
                else:
                    print("[GMAIL] No Greenhouse emails found yet...")

                # Wait before retrying
                print(f"[GMAIL] Waiting 5s before retry... ({int(asyncio.get_event_loop().time() - start_time)}s elapsed)")
                await page.wait_for_timeout(5000)

                # Refresh inbox
                await page.goto("https://mail.google.com/mail/u/0/#inbox")
                await page.wait_for_timeout(2000)

            print(f"\n[GMAIL] Timeout after {max_wait_seconds}s - no verification code found")
            return None

        except Exception as e:
            print(f"[GMAIL] Error: {e}")
            import traceback
            traceback.print_exc()
            return None
        finally:
            # Keep browser open briefly so user can see result
            await page.wait_for_timeout(2000)
            await browser.close()


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
    user_email = "ryanzhou147@gmail.com"
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
    
    # 1. LOCAL MODE: Always use local test data (database calls commented out)
    print(f"Using local test profile (LOCAL MODE - no database)...")
    user_profile = {
        "email": user_email,
        "first_name": "Ryan",
        "last_name": "Zhou",
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
    # DATABASE CODE COMMENTED OUT:
    # if args.local:
    #     ... (local profile above)
    # else:
    #     print(f"Retrieving user: {user_email}...")
    #     user_profile = await get_user(user_email)
    #
    #     if not user_profile:
    #         print(f"Error: User {user_email} not found in database.")
    #         print("Please run setup_demo.py first to create the test user, or use --local flag.")
    #         return
    
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
    

    async def auto_verification():
        """Automatically fetch 2FA code from Gmail using browser."""
        print("\n" + "!" * 50)
        print("2FA REQUIRED - AUTO-FETCHING FROM GMAIL")
        print("!" * 50)

        # Try automatic Gmail fetch
        code = await fetch_2fa_from_gmail(user_email, max_wait_seconds=120)

        if code:
            print(f"\n[AUTO-2FA] Successfully retrieved code: {code}")
            return code
        else:
            # Fallback to manual input if automatic fails
            print("\n[AUTO-2FA] Automatic fetch failed. Falling back to manual input...")
            return await asyncio.get_event_loop().run_in_executor(None, input, "Enter 8-digit code manually: ")

    result = await applier.fill_and_submit(
        url,
        fields,
        user_profile=user_profile,
        job_description=job_description,
        expected_fingerprint=None,  # Disable strict check for debug
        submit=args.submit,
        keep_open=args.keep_open,
        verification_callback=auto_verification
    )
    
    print("\nResult:", result)
    
    if args.submit and result.get("status") == "success":
        print(f"\n[OK] Application submitted! Check {user_email} for confirmation.")

    # LOCAL MODE: Database cleanup commented out
    # if not args.local:
    #     await close_database()

if __name__ == "__main__":
    asyncio.run(main())