"""Greenhouse job application form automation."""

import asyncio
import hashlib
import json
import os
import random
import re
from typing import Any

from playwright.async_api import async_playwright, Page, Browser

from app.ai import get_field_value
from app.rate_limiter import BROWSER_SEMAPHORE, ai_rate_limiter


# Standard field patterns for cache key matching
STANDARD_FIELD_PATTERNS: dict[str, str] = {
    r"first\s*name": "first_name",
    r"last\s*name": "last_name",
    r"email": "email",
    r"phone|telephone|mobile": "phone",
    r"linkedin": "linkedin_url",
    r"github": "github_url",
    r"portfolio|website": "website_url",
    r"years?\s*(of)?\s*experience": "years_of_experience",
    r"authorized?\s*(to)?\s*work": "work_authorization",
    r"sponsor(ship)?": "requires_sponsorship",
    r"gender": "gender",
    r"race|ethnicity": "race_ethnicity",
    r"veteran": "veteran_status",
    r"disability": "disability_status",
}


def get_cache_key(label: str) -> tuple[str, str]:
    """
    Get the cache key for a field label.

    Returns:
        Tuple of (cache_type, cache_key) where cache_type is 'standard' or 'custom'
    """
    normalized = label.lower().strip()

    # Check standard fields
    for pattern, key in STANDARD_FIELD_PATTERNS.items():
        if re.search(pattern, normalized):
            return ("standard", key)

    # Custom field - use hash
    question_hash = hashlib.md5(normalized.encode()).hexdigest()[:16]
    return ("custom", question_hash)


def compute_form_fingerprint(fields: list[dict[str, Any]]) -> str:
    """
    Compute a fingerprint of the form structure.

    Used to detect if form changed between analyze and submit.
    """
    # Sort fields by field_id for consistency
    sorted_fields = sorted(fields, key=lambda f: f.get("field_id", ""))

    # Create a signature from field structure (not values)
    signature_parts = []
    for f in sorted_fields:
        part = f"{f.get('field_id', '')}:{f.get('field_type', '')}:{f.get('label', '')}"
        if f.get("options"):
            part += ":" + ",".join(sorted(f["options"]))
        signature_parts.append(part)

    signature = "|".join(signature_parts)
    return hashlib.sha256(signature.encode()).hexdigest()[:16]


class GreenhouseApplier:
    """Handles Greenhouse job application form automation."""

    def __init__(self, headless: bool = True):
        self.headless = headless

    async def analyze_form(
        self,
        url: str,
        user_profile: dict[str, Any],
        job_description: str = "",
        cached_responses: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Analyze a job application form and generate recommended values.

        Does NOT fill or submit the form.

        Args:
            url: Job application URL
            user_profile: User's profile data
            job_description: Job description text for AI context
            cached_responses: User's cached form responses

        Returns:
            Dict with 'fields' list and 'form_fingerprint'
        """
        cached_responses = cached_responses or {"standard": {}, "custom": {}}

        async with BROWSER_SEMAPHORE:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=self.headless)
                try:
                    context = await browser.new_context()
                    page = await context.new_page()

                    await page.goto(url)

                    try:
                        await page.wait_for_selector("form", timeout=10000)
                    except Exception:
                        return {"status": "error", "message": "Form not found on page.", "fields": []}

                    # Wait for form to settle
                    await page.wait_for_timeout(2000)

                    # Extract all form fields
                    fields = await self._extract_form_fields(page)

                    # Generate recommendations for each field
                    await self._generate_recommendations(
                        fields, user_profile, job_description, cached_responses
                    )

                    # Compute fingerprint
                    fingerprint = compute_form_fingerprint(fields)

                    return {
                        "status": "success",
                        "fields": fields,
                        "form_fingerprint": fingerprint
                    }
                finally:
                    await browser.close()

    async def fill_and_submit(
        self,
        url: str,
        fields: list[dict[str, Any]],
        user_profile: dict[str, Any] | None = None,
        job_description: str = "",
        expected_fingerprint: str | None = None,
        submit: bool = True,
        keep_open: bool = False
    ) -> dict[str, Any]:
        """
        Fill and optionally submit a job application form.

        Args:
            url: Job application URL
            fields: List of fields with final_value set
            user_profile: Optional user profile for filling conditional fields
            job_description: Optional job description for AI context on conditional fields
            expected_fingerprint: If provided, verify form hasn't changed
            submit: Whether to click submit
            keep_open: Whether to keep browser open after completion (waits for user input)

        Returns:
            Result dict with status and message
        """
        async with BROWSER_SEMAPHORE:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=self.headless)
                try:
                    context = await browser.new_context()
                    page = await context.new_page()

                    await page.goto(url)

                    try:
                        await page.wait_for_selector("form", timeout=10000)
                    except Exception:
                        return {"status": "error", "message": "Form not found on page."}

                    # Verify fingerprint if provided
                    if expected_fingerprint:
                        current_fields = await self._extract_form_fields(page)
                        current_fingerprint = compute_form_fingerprint(current_fields)
                        if current_fingerprint != expected_fingerprint:
                            return {
                                "status": "form_changed",
                                "message": "Form structure has changed since analysis. Please re-analyze."
                            }

                    # Fill all known fields
                    await self._fill_form_fields(page, fields, user_profile=user_profile)

                    # --- SECOND PASS: CHECK FOR NEW FIELDS (Conditional Logic) ---
                    if user_profile:
                        # Wait a moment for UI to update (e.g. Race field appearing)
                        await page.wait_for_timeout(1000)
                        
                        current_fields = await self._extract_form_fields(page)
                        existing_ids = set(f.get("field_id") for f in fields)
                        
                        # Identify truly new fields
                        new_fields = []
                        for f in current_fields:
                            if f.get("field_id") not in existing_ids:
                                # Also check if we accidentally missed it by ID but matched by selector?
                                # Ideally field_id is unique enough.
                                new_fields.append(f)
                        
                        if new_fields:
                            print(f"Detected {len(new_fields)} new fields after initial fill. Attempting to fill...")
                            # Generate values for new fields
                            # We pass empty cache for now as we don't want to block on cache lookup for dynamic fields
                            await self._generate_recommendations(new_fields, user_profile, job_description, {"standard": {}, "custom": {}})
                            
                            # Promote recommended to final
                            for nf in new_fields:
                                if not nf.get("final_value"):
                                    nf["final_value"] = nf.get("recommended_value")
                            
                            # Fill new fields
                            await self._fill_form_fields(page, new_fields, user_profile=user_profile)
                    # -------------------------------------------------------------

                    result = {"status": "dry_run", "message": "Form filled, submit skipped."}
                    if submit:
                        result = await self._submit_form(page)
                    
                    if keep_open:
                        print(f"\nBrowser kept open. Status: {result['status']}")
                        print("Press Enter to close browser and finish...")
                        await asyncio.get_event_loop().run_in_executor(None, input)
                        
                    return result
                finally:
                    await browser.close()

    async def _extract_form_fields(self, page: Page) -> list[dict[str, Any]]:
        """Extract all form fields from the page."""
        fields: list[dict[str, Any]] = []
        field_counter = 0

        # 1. Handle React-Select / custom dropdowns
        custom_selects = await page.query_selector_all(".select__control, div[role='combobox']")
        for cs in custom_selects:
            try:
                # Debug logging for visibility
                is_visible = await cs.is_visible()
                if not is_visible:
                    # Try to identify what we are skipping
                    selector_debug = await self._get_unique_selector(cs)
                    print(f"DEBUG: Skipping invisible react-select: {selector_debug}")
                    continue

                # Try to get the associated input
                inp = await cs.query_selector("input")
                field_id = None
                if inp:
                    field_id = await inp.get_attribute("id") or await inp.get_attribute("name")

                if not field_id:
                    field_id = f"react_select_{field_counter}"
                    field_counter += 1

                # Get label
                label = await self._get_field_label(page, cs, field_id)

                # Try to get options by clicking and reading menu
                options = await self._get_react_select_options(page, cs)

                # Get selector for this element
                selector = await self._get_unique_selector(cs)

                fields.append({
                    "field_id": field_id,
                    "selector": selector,
                    "label": label or field_id,
                    "field_type": "react_select",
                    "required": False,  # Hard to determine for react-select
                    "options": options,
                    "recommended_value": None,
                    "final_value": None,
                    "source": "manual",
                    "confidence": 0.0,
                    "reasoning": None
                })
            except Exception as e:
                print(f"Error extracting react-select: {e}")

        # 2. Handle standard inputs, textareas, selects
        elements = await page.query_selector_all(
            "input:not([type='hidden']):not([type='submit']):not([type='button']):not([type='reset']), "
            "textarea, select"
        )

        for el in elements:
            try:
                if not await el.is_visible():
                    # File inputs might be hidden but still usable
                    type_attr = await el.get_attribute("type")
                    if type_attr != "file":
                        # print(f"DEBUG: Skipping invisible input: {await self._get_unique_selector(el)}")
                        continue

                # Skip elements that are effectively hidden (accessibility/react-select helpers)
                aria_hidden = await el.get_attribute("aria-hidden")
                if aria_hidden == "true":
                    continue
                
                class_name = await el.get_attribute("class") or ""
                if "requiredInput" in class_name:
                    continue

                # Skip if inside a react-select (already handled)
                is_react_child = await el.evaluate("""e => {
                    return !!e.closest('.select__control') || !!e.closest('div[role="combobox"]');
                }""")
                if is_react_child:
                    continue

                tag_name = await el.evaluate("e => e.tagName.toLowerCase()")
                type_attr = await el.get_attribute("type") or "text"
                field_id = await el.get_attribute("id") or await el.get_attribute("name")

                if not field_id:
                    field_id = f"{tag_name}_{field_counter}"
                    field_counter += 1

                # Skip certain types
                if type_attr in ["checkbox", "radio", "image"]:
                    continue

                # Determine field type
                if tag_name == "select":
                    field_type = "select"
                elif tag_name == "textarea":
                    field_type = "textarea"
                elif type_attr == "file":
                    field_type = "file"
                else:
                    field_type = "text"

                # Get label
                label = await self._get_field_label(page, el, field_id)

                # Get options for select
                options = None
                if field_type == "select":
                    options = await self._get_select_options(el)

                # Check if required
                required = await el.get_attribute("required") is not None
                aria_required = await el.get_attribute("aria-required")
                if aria_required == "true":
                    required = True

                # Get selector
                selector = await self._get_unique_selector(el)

                fields.append({
                    "field_id": field_id,
                    "selector": selector,
                    "label": label or field_id,
                    "field_type": field_type,
                    "required": required,
                    "options": options,
                    "recommended_value": None,
                    "final_value": None,
                    "source": "manual",
                    "confidence": 0.0,
                    "reasoning": None
                })
            except Exception as e:
                print(f"Error extracting field: {e}")

        return fields

    async def _get_field_label(self, page: Page, element, field_id: str | None) -> str:
        """Get the label text for a form field."""
        label_text = ""

        # 0. Greenhouse specific: Look for parent .input-wrapper's label
        # This is very common in Greenhouse forms
        label_text = await element.evaluate("""e => {
            const wrapper = e.closest('.input-wrapper');
            if (wrapper) {
                const label = wrapper.querySelector('label');
                if (label) return label.innerText;
            }
            return '';
        }""")
        
        if label_text:
            return label_text.strip()

        # 1. Try 'for' attribute
        if field_id:
            labels = await page.query_selector_all(f"label[for='{field_id}']")
            if labels:
                label_text = await labels[0].text_content() or ""

        # 2. Try aria-labelledby
        if not label_text:
            aria_labelledby = await element.get_attribute("aria-labelledby")
            if aria_labelledby:
                lbl_el = await page.query_selector(f"#{aria_labelledby}")
                if lbl_el:
                    label_text = await lbl_el.text_content() or ""

        # 3. Try aria-label
        if not label_text:
            label_text = await element.get_attribute("aria-label") or ""

        # 4. Try placeholder
        if not label_text:
            label_text = await element.get_attribute("placeholder") or ""

        # 5. Try closest label (generic fallback)
        if not label_text:
            label_text = await element.evaluate("""e => {
                let label = e.closest('label');
                if (!label) {
                    const container = e.closest('.field, .form-group');
                    if (container) {
                        label = container.querySelector('label');
                    }
                }
                return label ? label.innerText : '';
            }""") or ""

        return label_text.strip()

    async def _get_select_options(self, select_element) -> list[str]:
        """Get options from a standard select element."""
        options = []
        option_elements = await select_element.query_selector_all("option")
        for opt in option_elements:
            text = await opt.text_content()
            value = await opt.get_attribute("value")
            # Prefer text, fall back to value
            opt_text = (text or value or "").strip()
            if opt_text:
                options.append(opt_text)
        return options

    async def _get_react_select_options(self, page: Page, control_element) -> list[str]:
        """Try to get options from a React-Select dropdown."""
        options = []
        try:
            # Click to open menu
            await control_element.click()
            await page.wait_for_timeout(300)

            # Look for menu options
            option_els = await page.query_selector_all(
                ".select__option, [class*='option'], div[id*='option']"
            )

            for opt in option_els[:20]:  # Limit to prevent too many
                if await opt.is_visible():
                    text = await opt.text_content()
                    if text:
                        options.append(text.strip())

            # Press Escape to close menu
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(100)
        except Exception as e:
            print(f"Error getting react-select options: {e}")

        return options

    async def _get_unique_selector(self, element) -> str:
        """Generate a unique CSS selector for an element."""
        try:
            # Try ID first
            el_id = await element.get_attribute("id")
            if el_id:
                return f"#{el_id}"

            # Try name
            name = await element.get_attribute("name")
            tag = await element.evaluate("e => e.tagName.toLowerCase()")
            if name:
                return f"{tag}[name='{name}']"

            # Fall back to generating a path
            selector = await element.evaluate("""e => {
                const path = [];
                while (e) {
                    if (e.id) {
                        path.unshift('#' + e.id);
                        break;
                    }
                    let selector = e.tagName.toLowerCase();
                    if (e.parentElement) {
                        const siblings = Array.from(e.parentElement.children).filter(
                            s => s.tagName === e.tagName
                        );
                        if (siblings.length > 1) {
                            selector += ':nth-of-type(' + (siblings.indexOf(e) + 1) + ')';
                        }
                    }
                    path.unshift(selector);
                    e = e.parentElement;
                }
                return path.join(' > ');
            }""")
            return selector
        except Exception:
            return ""

    async def _generate_recommendations(
        self,
        fields: list[dict[str, Any]],
        user_profile: dict[str, Any],
        job_description: str,
        cached_responses: dict[str, Any]
    ):
        """Generate AI recommendations for each field."""
        tasks = []

        for field in fields:
            # Skip file fields - handled separately
            if field["field_type"] == "file":
                field["recommended_value"] = "[Resume will be uploaded]"
                field["source"] = "profile"
                field["confidence"] = 1.0
                continue

            label = field["label"]
            cache_type, cache_key = get_cache_key(label)

            # Check profile first for core fields
            profile_value = self._get_profile_value(field, user_profile)
            if profile_value:
                field["recommended_value"] = profile_value
                field["source"] = "profile"
                field["confidence"] = 1.0
                field["reasoning"] = "From your profile"
                continue

            # Check cached responses
            if cache_type == "standard":
                cached_value = cached_responses.get("standard", {}).get(cache_key)
                if cached_value:
                    field["recommended_value"] = cached_value
                    field["source"] = "cached"
                    field["confidence"] = 0.9
                    field["reasoning"] = "Previously used answer"
                    continue
            else:
                custom_cache = cached_responses.get("custom", {}).get(cache_key)
                if custom_cache:
                    field["recommended_value"] = custom_cache.get("answer")
                    field["source"] = "cached"
                    field["confidence"] = 0.9
                    field["reasoning"] = "Previously used answer"
                    continue

            # Need AI for this field
            tasks.append(self._get_ai_recommendation(field, user_profile, job_description))

        # Run AI tasks concurrently
        if tasks:
            await asyncio.gather(*tasks)

    def _get_profile_value(self, field: dict[str, Any], profile: dict[str, Any]) -> str | None:
        """Try to get a value directly from the user profile."""
        label_lower = field["label"].lower()
        field_id_lower = str(field.get("field_id", "")).lower()

        # Direct mappings
        mappings = {
            "first_name": ["first name", "firstname", "first_name"],
            "last_name": ["last name", "lastname", "last_name"],
            "email": ["email", "e-mail"],
            "phone": ["phone", "telephone", "mobile"],
            "linkedin_url": ["linkedin"],
            "github_url": ["github"],
            "website_url": ["website", "portfolio"],
            "location": ["location", "address"],
            "race": ["race", "ethnicity", "latino", "hispanic"],
            "gender": ["gender", "sex"],
            "veteran_status": ["veteran"],
            "disability": ["disability", "handicap"],
            "authorization": ["authorized to work", "work authorization", "visa"],
            "sponsorship": ["sponsorship", "sponsor"],
        }

        for profile_key, patterns in mappings.items():
            for pattern in patterns:
                if pattern in label_lower or pattern in field_id_lower:
                    value = profile.get(profile_key)
                    if value:
                        # Debug match
                        # print(f"Matched field '{field['label']}' to profile key '{profile_key}' via pattern '{pattern}'")
                        return str(value)

        return None

    async def _get_ai_recommendation(
        self,
        field: dict[str, Any],
        user_profile: dict[str, Any],
        job_description: str
    ):
        """Get AI recommendation for a single field."""
        await ai_rate_limiter.acquire()

        # Build context string
        context_parts = [f"Type: {field['field_type']}"]
        if field.get("options"):
            context_parts.append(f"Options: {json.dumps(field['options'])}")
        context_str = ", ".join(context_parts)

        try:
            value = await get_field_value(
                field["label"],
                context_str,
                user_profile,
                job_description
            )

            if value:
                field["recommended_value"] = value
                field["source"] = "ai"
                field["confidence"] = 0.7
                field["reasoning"] = "AI-generated based on your profile"

                # For dropdowns, verify the value matches an option
                if field.get("options") and value not in field["options"]:
                    # Try to find closest match
                    value_lower = value.lower()
                    for opt in field["options"]:
                        if value_lower in opt.lower() or opt.lower() in value_lower:
                            field["recommended_value"] = opt
                            field["reasoning"] = f"AI suggested '{value}', matched to '{opt}'"
                            break
        except Exception as e:
            print(f"AI error for field {field['label']}: {e}")
            field["confidence"] = 0.0

    async def _fill_form_fields(self, page: Page, fields: list[dict[str, Any]], user_profile: dict[str, Any] | None = None):
        """Fill all form fields with their final values."""
        
        # 1. Determine Country Hint for Phone Fields
        country_hint = None
        explicit_country_field_exists = False
        
        for field in fields:
            label = field.get("label", "").lower()
            val = field.get("final_value") or field.get("recommended_value")
            if "country" in label and val:
                # Extract name before any code: "United States +1" -> "United States"
                country_hint = val.split('+')[0].strip()
                explicit_country_field_exists = True
                break
        
        if not country_hint and user_profile:
            # Try to infer from location
            loc = user_profile.get("location", "").lower()
            if "usa" in loc or "united states" in loc:
                country_hint = "United States"
            elif "canada" in loc:
                country_hint = "Canada"
            elif "uk" in loc or "united kingdom" in loc:
                country_hint = "United Kingdom"
        
        if country_hint:
            print(f"Debug: Country hint for phone fields: {country_hint} (Explicit field: {explicit_country_field_exists})")

        # 2. Fill fields
        for field in fields:
            value = field.get("final_value") or field.get("recommended_value")
            label = field.get("label")
            
            if not value:
                if field.get("required"):
                    print(f"Skipping required field with NO value: '{label}'")
                else:
                    # Optional field with no value
                    pass
                continue

            print(f"Filling field '{label}' (Type: {field['field_type']}) with value: '{str(value)[:50]}...'")
            
            selector = field.get("selector")
            field_type = field.get("field_type")

            try:
                if field_type == "file":
                    await self._fill_file_field(page, selector, value)
                elif field_type == "react_select":
                    await self._fill_react_select(page, selector, value, label)
                elif field_type == "select":
                    await self._fill_standard_select(page, selector, value)
                else:
                    # Pass explicit_country_field_exists to avoid double-setting flag
                    await self._fill_text_field(
                        page, 
                        selector, 
                        value, 
                        country_hint=country_hint, 
                        skip_iti_flag=explicit_country_field_exists
                    )
            except Exception as e:
                print(f"Error filling {label}: {e}")

    async def _fill_text_field(self, page: Page, selector: str, value: str, country_hint: str | None = None, skip_iti_flag: bool = False):
        """Fill a text input or textarea."""
        if not selector:
            return
            
        locator = page.locator(selector).first
        if await locator.count() > 0 and await locator.is_visible():
            await locator.scroll_into_view_if_needed()
            
            # Special handling for phone fields (often use intl-tel-input which needs typing)
            is_phone = "phone" in selector.lower() or await locator.get_attribute("type") == "tel"
            
            if is_phone:
                # Handle intl-tel-input (iti) dropdown if present
                try:
                    # Look for the iti container wrapping this input
                    iti_container = page.locator(".iti").filter(has=locator).first
                    if await iti_container.count() > 0:
                        selected_country_btn = iti_container.locator(".iti__selected-country").first
                        if await selected_country_btn.count() > 0:
                            # Only attempt to change country if:
                            # 1. We are NOT skipping flag (no separate country field)
                            # 2. Value doesn't have a '+' prefix (which might imply full international format)
                            # 3. We have a hint
                            if not skip_iti_flag and not str(value).startswith("+") and country_hint:
                                await selected_country_btn.click()
                                await page.wait_for_timeout(300)
                                
                                # ITI usually has a search input in the dropdown
                                search_input = page.locator(".iti__search-input").first
                                if await search_input.count() > 0 and await search_input.is_visible():
                                    await search_input.fill(country_hint)
                                    await page.wait_for_timeout(500)
                                    await page.keyboard.press("Enter")
                                    await page.wait_for_timeout(300)
                except Exception as e:
                    print(f"Debug: Failed to set ITI country code: {e}")

                await locator.click()
                await locator.clear()
                # Use sequences for phone numbers to trigger any mask/formatting logic
                await locator.press_sequentially(str(value), delay=50)
            else:
                await locator.fill(str(value))
        else:
             print(f"Text field not found: {selector}")

    async def _fill_standard_select(self, page: Page, selector: str, value: str):
        """Fill a standard HTML select element."""
        if not selector:
            return

        locator = page.locator(selector).first
        if await locator.count() == 0:
            print(f"Select field not found: {selector}")
            return
            
        # Try to select by visible text first, then by value
        try:
            await locator.select_option(label=value)
        except Exception:
            try:
                await locator.select_option(value=value)
            except Exception:
                # Try partial match
                # Use evaluate to find the matching option
                option_val = await locator.evaluate(f"""(select, text) => {{
                    const options = Array.from(select.options);
                    const match = options.find(o => o.text.toLowerCase().includes(text.toLowerCase()));
                    return match ? match.value : null;
                }}""", value)
                
                if option_val:
                    await locator.select_option(value=option_val)

    async def _fill_react_select(self, page: Page, selector: str, value: str, label: str = ""):
        """Fill a React-Select component."""
        # Strategy: Use Locator with multiple fallback selectors
        target = None
        
        # 1. Try the specific selector
        if selector:
            target = page.locator(selector).first
            if not await target.is_visible():
                target = None

        # 2. Try by Label if selector failed
        if not target and label:
            try:
                label_el = page.get_by_text(label, exact=True).first
                if await label_el.count() > 0:
                     # Go up to a container that has a select__control
                     target = label_el.locator("xpath=ancestor::div[contains(@class, 'field') or contains(@class, 'input-wrapper')]//div[contains(@class, 'select__control')]").first
            except Exception:
                pass

        if not target or not await target.is_visible():
             if selector:
                 print(f"React select not found by selector: {selector}")
             return

        await target.scroll_into_view_if_needed()
        
        # Determine if this is likely an async field
        field_id = await target.get_attribute("id") or ""
        field_info_str = (selector + " " + label + " " + field_id).lower()
        is_async = "location" in field_info_str or "city" in field_info_str or "school" in field_info_str or "university" in field_info_str
        
        try:
            # 1. Click to open menu
            await target.click()
            await page.wait_for_timeout(300)

            # 2. Check if we should type first (Async or Long List)
            # Quick check for option count
            option_count = await page.locator(".select__option, [class*='option'], div[id*='option']").count()
            should_type_first = is_async or option_count > 20

            if should_type_first:
                # Type to filter
                await page.keyboard.type(value, delay=50)
                await page.wait_for_timeout(1500 if is_async else 500)
            
            # 3. Iterate visible options to find a match and CLICK it
            option_els = await page.locator(".select__option, [class*='option'], div[id*='option']").all()
            
            # Keywords for "Decline" / "Prefer not to answer"
            decline_keywords = ["decline", "prefer not", "do not wish", "not specify", "wish to answer"]
            val_lower = value.lower()
            is_decline_value = any(k in val_lower for k in decline_keywords)
            
            best_match_el = None
            debug_options = []

            # Collect all options first to make better decision
            visible_options = []
            for opt in option_els:
                if await opt.is_visible():
                    text = await opt.text_content()
                    if text:
                        visible_options.append((text.strip(), opt))
                        debug_options.append(text.strip())

            # Decision Logic
            match_found = False
            
            # 1. Priority: Decline explicitly
            if is_decline_value:
                for text, opt in visible_options:
                    if any(k in text.lower() for k in decline_keywords):
                        best_match_el = opt
                        match_found = True
                        break
            
            # 2. Exact Match
            if not match_found:
                for text, opt in visible_options:
                    if val_lower == text.lower():
                        best_match_el = opt
                        match_found = True
                        break
            
            # 3. Fuzzy/Substring (Restricted)
            if not match_found:
                for text, opt in visible_options:
                    opt_lower = text.lower()
                    # Only allow substring if option is long enough (>3 chars) OR value is very short?
                    # "No" is short. "Prefer not to answer" is long.
                    # if "No" in "Prefer not to answer" -> BAD.
                    # if "US" in "USA" -> OK.
                    
                    # Logic: 
                    # If VAL contains OPT (e.g. Val="I am Hispanic", Opt="Hispanic") -> Match
                    # If OPT contains VAL (e.g. Val="Hispanic", Opt="I am Hispanic") -> Match
                    
                    # BUT guard against "No" in "Prefer NOT..."
                    # We can use word boundary check or length check.
                    
                    # Simple heuristic:
                    # If option is "No", only match if value IS "No". (Handled by Exact Match above)
                    # So here, if opt_lower == "no" or opt_lower == "yes", SKIP substring check.
                    if opt_lower in ["no", "yes"]:
                        continue
                        
                    if val_lower in opt_lower or opt_lower in val_lower:
                        best_match_el = opt
                        match_found = True
                        break

            if best_match_el:
                await best_match_el.click()
                return

            # If we typed but didn't find a clickable match, maybe try Enter (for free text)
            if should_type_first:
                await page.keyboard.press("Enter")
                return
            
            # If we didn't type (short list) and didn't find match, print warning
            print(f"Warning: Value '{value}' not found in options for {label}. Options: {debug_options[:10]}...")
            await page.keyboard.press("Escape")

        except Exception as e:
            print(f"Error filling react-select {label}: {e}")

    async def _fill_file_field(self, page: Page, selector: str, value: str):
        """Fill a file upload field."""
        if not selector:
            return
            
        locator = page.locator(selector).first
        if await locator.count() > 0:
            # Value should be a file path
            if os.path.exists(value):
                await locator.set_input_files(value)
            else:
                print(f"File not found: {value}")
        else:
            print(f"File input not found: {selector}")


    async def _submit_form(self, page: Page) -> dict[str, Any]:
        """Submit the form and wait for confirmation."""
        # Find submit button
        submit_btn = await page.query_selector("#submit_app")
        if not submit_btn:
            submit_btn = await page.query_selector("input[type='submit']")
        if not submit_btn:
            submit_btn = await page.query_selector("button[type='submit']")

        if not submit_btn:
            return {"status": "error", "message": "Submit button not found."}

        await submit_btn.click()

        try:
            await page.wait_for_selector("#application_confirmation", timeout=15000)
            return {"status": "success", "message": "Application submitted successfully."}
        except Exception:
            # Check if we're on a different confirmation page
            current_url = page.url
            if "thank" in current_url.lower() or "confirm" in current_url.lower():
                return {"status": "success", "message": "Application submitted (confirmation page detected)."}
            return {"status": "unknown", "message": "Submit clicked but confirmation not detected."}

    # Legacy method for backwards compatibility
    async def apply(
        self,
        url: str,
        candidate_data: dict[str, Any],
        submit: bool = False,
        keep_open: bool = False,
        debug_fields: bool = False,
        job_description: str = ""
    ) -> dict[str, Any]:
        """
        Legacy method - applies to a job using the old approach.

        For new code, use analyze_form() + fill_and_submit() instead.
        """
        # Convert candidate_data to expected format
        user_profile = candidate_data

        # Analyze form
        analysis = await self.analyze_form(
            url=url,
            user_profile=user_profile,
            job_description=job_description,
            cached_responses=None
        )

        if analysis.get("status") == "error":
            return analysis

        # Set final values from recommendations
        fields = analysis.get("fields", [])
        for field in fields:
            field["final_value"] = field.get("recommended_value")

        # Fill and optionally submit
        result = await self.fill_and_submit(
            url=url,
            fields=fields,
            expected_fingerprint=None,  # Skip fingerprint check for legacy
            submit=submit
        )

        return result
