"""
Purpose:
Downloads a repository snapshot (tarball) from GitHub for processing.

Responsibilities:
- Authenticate with the GitHub API using an installation token.
- Fetch the repository tarball archive.
- Extract the archive to a temporary directory.
"""

import os
import tarfile
import tempfile
import httpx
from typing import Optional

def download_and_extract_repo(owner: str, repo: str, installation_token: str, ref: str = "") -> str:
    """
    Downloads a repository tarball from GitHub and extracts it to a temporary directory.
    Returns the path to the extracted repository root.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/tarball/{ref}"
    headers = {
        "Authorization": f"Bearer {installation_token}",
        "Accept": "application/vnd.github.v3+json"
    }

    tmp_dir = tempfile.mkdtemp(prefix=f"teslalab_{repo}_")
    tarball_path = os.path.join(tmp_dir, "repo.tar.gz")

    print(f"Downloading {owner}/{repo} to {tarball_path}...")
    
    with httpx.stream("GET", url, headers=headers, follow_redirects=True) as response:
        response.raise_for_status()
        with open(tarball_path, "wb") as f:
            for chunk in response.iter_bytes():
                f.write(chunk)
                
    print("Extracting tarball...")
    extract_dir = os.path.join(tmp_dir, "extracted")
    os.makedirs(extract_dir, exist_ok=True)
    
    with tarfile.open(tarball_path, "r:gz") as tar:
        tar.extractall(path=extract_dir)
        
    # GitHub tarballs extract into a subfolder named like owner-repo-sha
    # We need to find that root folder
    subdirs = os.listdir(extract_dir)
    if not subdirs:
        raise Exception("Tarball extraction failed: No directories found")
        
    repo_root = os.path.join(extract_dir, subdirs[0])
    print(f"Repository extracted to {repo_root}")
    
    return repo_root
