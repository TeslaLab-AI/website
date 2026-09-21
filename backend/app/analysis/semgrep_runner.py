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
        try:
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True,
                encoding="utf-8",
                shell=is_windows,
                timeout=300
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            raise RuntimeError(f"Semgrep execution failed: {e}") from e
            
        # Semgrep returns 0 for no findings, 1 for findings, and >=2 for errors.
        if result.returncode >= 2:
            raise RuntimeError(f"Semgrep exited with error code {result.returncode}. Stderr: {result.stderr}")
        
        output = result.stdout
        if not output and result.stderr:
            print(f"Semgrep stderr: {result.stderr}")
            
        if not output:
            raise RuntimeError(f"Semgrep produced no output. Stderr: {result.stderr}")
            
        try:
            data = json.loads(output)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Failed to parse Semgrep JSON output: {output}") from e
            
        findings = []
        for result_item in data.get("results", []):
            extra = result_item.get("extra", {})
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
            rule_id = result_item.get("check_id", "").lower()
            if "supply-chain" in rule_id or "supply-chain" in rule_category:
                category = "dependencies"
            elif "security" in rule_category or "cwe" in metadata:
                category = "security"
                
            file_path = result_item.get("path", "")
            # Make path relative to target_dir if possible
            if file_path.startswith(target_dir):
                file_path = os.path.relpath(file_path, target_dir)
                
            findings.append({
                "category": category,
                "severity": severity,
                "title": result_item.get("check_id", "Semgrep Finding").split(".")[-1], # Use the last part of the rule ID
                "description": extra.get("message", "No description provided."),
                "file_path": file_path,
                "line_number": result_item.get("start", {}).get("line", 0)
            })
            
        return findings
        
    except Exception as e:
        print(f"Warning: Semgrep failed or is not installed. Skipping static analysis. Error: {e}")
        return []
