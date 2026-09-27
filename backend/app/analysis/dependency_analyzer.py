"""
Purpose:
Analyzes dependency files in a repository.

Responsibilities:
- Find and parse package.json (Node/JS).
- Find and parse requirements.txt (Python).
- Extract dependencies and map them to our findings format.
"""
import os
import json
from typing import List, Dict, Any
from pathlib import Path

def analyze_dependencies(target_dir: str) -> List[Dict[str, Any]]:
    """
    Scans the repository for dependency files and extracts dependencies.
    """
    print(f"Running Dependency Analysis on {target_dir}...")
    findings = []
    
    target_path = Path(target_dir)
    
    # 1. Parse package.json
    for pjson_path in target_path.rglob("package.json"):
        if "node_modules" in str(pjson_path):
            continue
            
        try:
            with open(pjson_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                
            deps = data.get("dependencies", {})
            dev_deps = data.get("devDependencies", {})
            
            rel_path = str(pjson_path.relative_to(target_path))
            
            # Combine them for simple reporting
            all_deps = {**deps, **dev_deps}
            for pkg, version in all_deps.items():
                findings.append({
                    "category": "dependencies",
                    "severity": "low", # In a real app, query OSV database to determine if it's critical
                    "title": f"Dependency: {pkg}",
                    "description": f"Version required: {version}",
                    "file_path": rel_path,
                    "line_number": 0
                })
        except Exception as e:
            print(f"Failed to parse {pjson_path}: {e}")
            
    # 2. Parse requirements.txt
    for req_path in target_path.rglob("requirements.txt"):
        if "venv" in str(req_path):
            continue
            
        try:
            with open(req_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                
            rel_path = str(req_path.relative_to(target_path))
            
            for i, line in enumerate(lines):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                    
                findings.append({
                    "category": "dependencies",
                    "severity": "low",
                    "title": f"Dependency: {line.split('==')[0].split('>=')[0]}",
                    "description": f"Requirement: {line}",
                    "file_path": rel_path,
                    "line_number": i + 1
                })
        except Exception as e:
            print(f"Failed to parse {req_path}: {e}")
            
    return findings
