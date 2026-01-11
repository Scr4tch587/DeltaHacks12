"""
HLS playlist rewriting module.
Rewrites playlists to point URIs to our API gateway endpoints.
"""
import re
from urllib.parse import urlparse


def normalize_path(path: str) -> str:
    """
    Normalize a path using POSIX rules, preventing directory traversal.
    
    Args:
        path: Path string to normalize
    
    Returns:
        Normalized path
    """
    # Remove leading/trailing slashes for processing
    path = path.strip('/')
    
    # Split into components
    parts = []
    for part in path.split('/'):
        if part == '.':
            continue
        elif part == '..':
            if parts:
                parts.pop()
        elif part:
            parts.append(part)
    
    return '/'.join(parts)


def resolve_hls_uri(playlist_key: str, uri_line: str, base_prefix: str = "hls/") -> str:
    """
    Resolve a URI line from a playlist against the playlist's directory.
    
    Args:
        playlist_key: The S3 key of the playlist (e.g., "hls/abc/master.m3u8")
        uri_line: The URI line from the playlist (can be relative or absolute)
        base_prefix: Base prefix that must be present in resolved keys (default: "hls/")
    
    Returns:
        Resolved S3 key (normalized, must start with base_prefix)
    
    Raises:
        ValueError: If the resolved key escapes the base_prefix (path traversal)
    """
    # Strip whitespace and decode if needed
    uri_line = uri_line.strip()
    
    # Parse the URI
    parsed = urlparse(uri_line)
    
    # If it's an absolute URL
    if parsed.scheme in ('http', 'https'):
        # If it points to our API already, extract the key
        # For now, we'll leave absolute URLs as-is if they don't match our pattern
        # This handles external URLs
        return uri_line
    
    # It's a relative URI - resolve against playlist directory
    playlist_dir = '/'.join(playlist_key.split('/')[:-1])  # Remove filename
    if not playlist_dir:
        playlist_dir = ''
    
    # Join the playlist directory with the URI
    if uri_line.startswith('/'):
        # Absolute path from bucket root
        resolved = uri_line.lstrip('/')
    else:
        # Relative path
        if playlist_dir:
            resolved = f"{playlist_dir}/{uri_line}"
        else:
            resolved = uri_line
    
    # Normalize the path
    resolved = normalize_path(resolved)
    
    # Security check: ensure it starts with base_prefix
    if not resolved.startswith(base_prefix):
        raise ValueError(f"Resolved key '{resolved}' escapes base prefix '{base_prefix}'")
    
    return resolved


def rewrite_playlist(text: str, playlist_key: str, api_base: str) -> str:
    """
    Rewrite an HLS playlist to point URIs to our API gateway.
    
    Args:
        text: Playlist content as UTF-8 string
        playlist_key: S3 key of the playlist (e.g., "hls/abc/master.m3u8")
        api_base: Base URL for the API (e.g., "http://localhost:8002" or "")
                  If empty, uses relative paths
    
    Returns:
        Rewritten playlist content
    """
    lines = text.split('\n')
    rewritten_lines = []
    
    # Pattern for EXT-X-KEY and EXT-X-MEDIA tags with URI="..."
    uri_in_tag_pattern = re.compile(r'(URI=)"([^"]+)"')
    
    for line in lines:
        original_line = line
        
        # Empty line - keep as-is
        if not line.strip():
            rewritten_lines.append(line)
            continue
        
        # Comment line (starts with #)
        if line.strip().startswith('#'):
            # Check if it's a tag with URI="..." (like #EXT-X-KEY:METHOD=AES-128,URI="key.key")
            if 'URI=' in line:
                # Rewrite URI in tag
                def replace_uri(match):
                    uri_attr = match.group(1)
                    uri_value = match.group(2)
                    
                    try:
                        resolved_key = resolve_hls_uri(playlist_key, uri_value)
                        
                        # If resolved_key is an absolute URL (external), keep it
                        if resolved_key.startswith('http://') or resolved_key.startswith('https://'):
                            return f'{uri_attr}"{uri_value}"'
                        
                        # Determine endpoint based on extension
                        if resolved_key.endswith('.m3u8'):
                            new_uri = f'{api_base}/hls/{resolved_key}' if api_base else f'/hls/{resolved_key}'
                        else:
                            new_uri = f'{api_base}/hls-seg/{resolved_key}' if api_base else f'/hls-seg/{resolved_key}'
                        
                        return f'{uri_attr}"{new_uri}"'
                    except ValueError:
                        # If resolution fails, keep original
                        return match.group(0)
                
                line = uri_in_tag_pattern.sub(replace_uri, line)
            rewritten_lines.append(line)
        else:
            # It's a URI line (not a comment, not empty)
            try:
                resolved_key = resolve_hls_uri(playlist_key, line.strip())
                
                # If resolved_key is an absolute URL (external), keep it
                if resolved_key.startswith('http://') or resolved_key.startswith('https://'):
                    rewritten_lines.append(line)
                    continue
                
                # Determine endpoint based on extension
                if resolved_key.endswith('.m3u8'):
                    new_uri = f'{api_base}/hls/{resolved_key}' if api_base else f'/hls/{resolved_key}'
                else:
                    new_uri = f'{api_base}/hls-seg/{resolved_key}' if api_base else f'/hls-seg/{resolved_key}'
                
                rewritten_lines.append(new_uri)
            except ValueError as e:
                # If resolution fails (e.g., path traversal), log and keep original
                # In production, you might want to log this as a warning
                rewritten_lines.append(original_line)
    
    return '\n'.join(rewritten_lines)
