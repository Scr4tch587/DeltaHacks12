"""Utilities for parsing job descriptions to extract company and position."""

import re
from typing import Tuple, Optional


def extract_company_and_position(job_description: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract company name and position title from job description.
    
    Args:
        job_description: Full job description text
        
    Returns:
        Tuple of (company_name, position_title) or (None, None) if not found
    """
    # Extract position from first line (before "About the job" or similar)
    first_line = job_description.split('\n')[0].strip()
    position = None
    
    if first_line and len(first_line) < 150:
        position = first_line
        # Remove year references like "2026"
        position = re.sub(r'\s*\d{4}\s*', ' ', position)
        # Format: "Summer Intern/Co-op 2026 – Agentic AI Developer" -> "Agentic AI Developer"
        # Remove season/intern prefixes
        position = re.sub(r'^(summer|winter|fall|spring)\s+(intern|co-op|coop)[\s/–-]*', '', position, flags=re.IGNORECASE)
        # Split on dash/em dash and take the last part (usually the actual position)
        if '–' in position:
            parts = position.split('–')
            if len(parts) > 1:
                position = parts[-1].strip()  # Take last part after dash
            else:
                position = parts[0].strip()
        elif '-' in position and not position.startswith('-'):
            parts = position.split('-')
            if len(parts) > 1:
                position = parts[-1].strip()  # Take last part after dash
            else:
                position = parts[0].strip()
        position = position.strip()
    
    # Extract company name
    company = None
    
    # Pattern 1: "About [Company] And [Company]" - most reliable
    # Match "About Manulife And John Hancock" -> "Manulife & John Hancock"
    # Look for the exact pattern on its own line, stop at end of line or newline
    about_line_match = re.search(r'^about\s+([A-Z][A-Za-z]+)(?:\s+(?:and|&)\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*))(?:\s*$|\s*\n)', job_description, re.IGNORECASE | re.MULTILINE)
    if about_line_match and about_line_match.group(2):
        # "About Manulife And John Hancock" -> "Manulife & John Hancock"
        company = f"{about_line_match.group(1).strip()} & {about_line_match.group(2).strip()}"
        company = company.strip()
        # Remove any newlines that might have been captured
        company = company.replace('\n', ' ').replace('\r', ' ')
        company = re.sub(r'\s+', ' ', company).strip()
    
    # Pattern 1b: "About [Company]" (single company) - look for it on its own line
    if not company:
        about_single_match = re.search(r'^about\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)', job_description, re.IGNORECASE | re.MULTILINE)
        if about_single_match:
            company = about_single_match.group(1)
            # Stop at "Financial", "Corporation", etc. - but only if they're on the same line
            company = re.sub(r'\s+(?:Financial|Corporation|Corp|Inc|LLC|Ltd|Company|is|are|we|our|the|a|an).*$', '', company, flags=re.IGNORECASE)
            company = company.strip()
    
    # Pattern 2: Look for "Company Financial Corporation" or similar (only if Pattern 1 didn't work)
    if not company:
        corp_match = re.search(r'([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)\s+(?:Financial\s+)?(?:Corporation|Corp|Inc|LLC|Ltd)', job_description)
        if corp_match:
            company = corp_match.group(1).strip()
    
    # Pattern 3: Look for company name mentioned in "At [Company]/[Company]" format
    if not company:
        at_slash_match = re.search(r'at\s+([A-Z][A-Za-z]+)/?([A-Z][A-Za-z]+)', job_description, re.IGNORECASE)
        if at_slash_match:
            if at_slash_match.group(2):
                company = f"{at_slash_match.group(1)} & {at_slash_match.group(2)}"
            else:
                company = at_slash_match.group(1)
            company = company.strip()
    
    # Final cleanup: ensure company doesn't contain extra words
    if company:
        # Split on common stop words and take first part
        company = re.sub(r'\s+(?:Financial|Corporation|Corp|Inc|LLC|Ltd|Company|is|are|we|our|the|a|an).*$', '', company, flags=re.IGNORECASE)
        company = company.strip()
    
    # Clean up position
    if position:
        # Remove any remaining year references
        position = re.sub(r'\s*\d{4}\s*', '', position)
        # Remove company name if it appears in position
        if company:
            for word in company.split():
                if len(word) > 3:  # Only remove substantial words
                    position = re.sub(r'\b' + re.escape(word) + r'\b', '', position, flags=re.IGNORECASE)
            position = re.sub(r'\s+', ' ', position).strip()
            position = re.sub(r'^\s*[–-]\s*', '', position)
        position = position.strip()
        # Limit length
        if len(position) > 50:
            position = position[:50].strip()
    
    return company, position


def generate_title(company: Optional[str], position: Optional[str], fallback: str = "Tech Job Opportunity") -> str:
    """
    Generate a title in format "Company - Position".
    
    Args:
        company: Company name (optional)
        position: Position title (optional)
        fallback: Fallback title if both are None
        
    Returns:
        Formatted title string
    """
    if company and position:
        return f"{company} - {position}"
    elif company:
        return f"{company} - Tech Position"
    elif position:
        return f"Tech Company - {position}"
    else:
        return fallback
