"""File search service using Windows Search API with PowerShell fallback."""
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def search_files(
    query: str,
    path: str | None = None,
    limit: int = 20,
) -> dict:
    """Search files by name on Windows.

    Tries Windows Search API first, falls back to PowerShell Get-ChildItem.

    Args:
        query: Filename pattern (supports * and ? wildcards)
        path: Directory to search (default: user profile)
        limit: Max results to return

    Returns:
        {"files": [...], "method": "wsearch"|"powershell", "count": N}
    """
    search_path = Path(path) if path else Path.home()

    # Try Windows Search API first
    try:
        files = _search_windows_search(query, str(search_path), limit)
        if files:
            return {"files": files, "method": "wsearch", "count": len(files)}
    except Exception as e:
        logger.debug("Windows Search failed: %s, falling back to PowerShell", e)

    # Fallback to PowerShell
    try:
        files = _search_powershell(query, str(search_path), limit)
        return {"files": files, "method": "powershell", "count": len(files)}
    except Exception as e:
        logger.error("PowerShell search also failed: %s", e)
        return {"files": [], "method": "none", "count": 0, "error": str(e)}


def _search_windows_search(query: str, path: str, limit: int) -> list[str]:
    """Search using Windows Search API (COM)."""
    import win32com.client

    # Build pattern - Windows Search uses % for LIKE, not *
    pattern = query.replace("*", "%").replace("?", "_")
    if "%" not in pattern and "_" not in pattern:
        pattern = f"%{pattern}%"

    # Normalize path for Windows Search
    # Windows Search expects URL format: file:C:/path or file://C:/path
    search_path = path.replace("\\", "/")
    if not search_path.endswith("/"):
        search_path += "/"

    conn = win32com.client.Dispatch("ADODB.Connection")
    rs = win32com.client.Dispatch("ADODB.Recordset")

    # Windows Search connection string
    conn.Open("Provider=Search.CollatorDSO;Extended Properties='Application=Windows';")

    # Build SQL query - use SCOPE for directory search
    sql = (
        f"SELECT TOP {limit} System.ItemPathDisplay "
        f"FROM SystemIndex "
        f"WHERE SCOPE='file:{search_path}' "
        f"AND System.FileName LIKE '{pattern}' "
        f"ORDER BY System.DateModified DESC"
    )

    logger.debug("Windows Search SQL: %s", sql)

    try:
        rs.Open(sql, conn)
        files = []
        while not rs.EOF:
            val = rs.Fields("System.ItemPathDisplay").Value
            if val:
                files.append(str(val))
            rs.MoveNext()
        rs.Close()
        return files
    finally:
        conn.Close()


def _search_powershell(query: str, path: str, limit: int) -> list[str]:
    """Fallback: search using PowerShell Get-ChildItem."""
    pattern = query if "*" in query or "?" in query else f"*{query}*"

    cmd = [
        "powershell", "-NoProfile", "-Command",
        f"Get-ChildItem -Path '{path}' -Filter '{pattern}' -Recurse -File -ErrorAction SilentlyContinue | "
        f"Select-Object -First {limit} -ExpandProperty FullName"
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

    if result.returncode != 0:
        raise RuntimeError(f"PowerShell error: {result.stderr.strip()}")

    files = [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
    return files
