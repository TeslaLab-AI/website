"""
Purpose:
Executes Semgrep static analysis on a codebase and parses the results.

Responsibilities:
- Run the Semgrep CLI via subprocess.
- Parse the resulting JSON.
- Map Semgrep findings (bugs, security) into our standardized format.
"""
import os
import json
import subprocess
from typing import List, Dict, Any

def run_semgrep(target_dir: str) -> List[Dict[str, Any]]:
    """
    Runs Semgrep with the 'auto' config on the target directory.
    Returns a list of standardized finding dictionaries.
    """
    print(f"Running Semgrep on {target_dir}...")
    
    # Comprehensive rule packs:
    # - p/default: standard bugs and code quality
    # - p/security-audit: security vulnerabilities (OWASP, CWE)
    # - p/supply-chain: dependency and package vulnerabilities (CVEs)
    cmd = [
        "semgrep", "scan",
        "--config", "p/default",
        "--config", "p/security-audit",
        "--config", "p/supply-chain",
        "--json",
        target_dir
    ]
    
    try:
        # Use shell=True on Windows if semgrep is a .cmd/.exe wrapper in the Scripts folder
        is_windows = os.name == 'nt'
        result = subprocess.run(
            cmd, 
            capture_output=True, 
            text=True,
            encoding="utf-8",
            shell=is_windows
        )
        
        output = result.stdout
        if not output and result.stderr:
            print(f"Semgrep stderr: {result.stderr}")
            
        if not output:
            print("Semgrep produced no output.")
            return []
            
        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            print("Failed to parse Semgrep JSON output.")
            return []
            
        findings = []
        for result in data.get("results", []):
            extra = result.get("extra", {})
            severity_str = extra.get("severity", "WARNING").upper()
            
            # Map Semgrep severity to our schema ('critical', 'high', 'medium', 'low')
            severity = "medium"
            if severity_str in ("CRITICAL",):
                severity = "critical"
            elif severity_str == "ERROR":
                severity = "high"
            elif severity_str == "INFO":
                severity = "low"
                
            # Classify category based on rule metadata
            # supply-chain rules use 'supply-chain' category, map those to 'dependencies'
            category = "bugs"
            metadata = extra.get("metadata", {})
            rule_category = metadata.get("category", "").lower()
            rule_id = result.get("check_id", "").lower()
            if "supply-chain" in rule_id or "supply-chain" in rule_category:
                category = "dependencies"
            elif "security" in rule_category or "cwe" in metadata:
                category = "security"
                
            file_path = result.get("path", "")
            # Make path relative to target_dir if possible
            if file_path.startswith(target_dir):
                file_path = os.path.relpath(file_path, target_dir)
                
            findings.append({
                "category": category,
                "severity": severity,
                "title": result.get("check_id", "Semgrep Finding").split(".")[-1], # Use the last part of the rule ID
                "description": extra.get("message", "No description provided."),
                "file_path": file_path,
                "line_number": result.get("start", {}).get("line", 0)
            })
            
        return findings
        
    except Exception as e:
        print(f"Error running Semgrep: {e}")
        return []
