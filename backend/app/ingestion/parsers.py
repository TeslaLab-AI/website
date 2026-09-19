import re
import json
import openai
from typing import Dict, Any
from app.contracts.schemas import BugFinding

def parse_sentry_payload(payload: Dict[str, Any]) -> BugFinding:
    """
    Parsers a standard Sentry crash JSON payload into a normalized BugFinding.
    Must perfectly preserve line numbers and stack frame hierarchy.
    """
    event_id = payload.get("event_id") or payload.get("id") or "unknown-sentry-id"
    
    # Extract Title and Description from metadata or exception
    exception_values = payload.get("exception", {}).get("values", [])
    title = payload.get("title")
    description = payload.get("metadata", {}).get("value")
    
    if not title and exception_values:
        title = exception_values[0].get("type", "UnknownException")
    if not description and exception_values:
        description = exception_values[0].get("value", "No description provided.")
        
    if not title:
        title = "Sentry Crash Report"
    if not description:
        description = "No description provided."

    # Extract Stack Trace and Files Hint
    stack_trace_lines = []
    files_hint = set()
    
    if exception_values:
        for exc in exception_values:
            frames = exc.get("stacktrace", {}).get("frames", [])
            if frames:
                stack_trace_lines.append(f"{exc.get('type', 'Exception')}: {exc.get('value', '')}")
                for frame in frames:
                    filename = frame.get("filename") or frame.get("abs_path") or "unknown_file"
                    lineno = frame.get("lineno", "?")
                    func = frame.get("function", "?")
                    module = frame.get("module", "?")
                    
                    line = f"  File \"{filename}\", line {lineno}, in {func}"
                    if frame.get("context_line"):
                        line += f"\n    {frame['context_line'].strip()}"
                    
                    stack_trace_lines.append(line)
                    if filename != "unknown_file":
                        files_hint.add(filename)
                        
    stack_trace = "\n".join(stack_trace_lines) if stack_trace_lines else None
    
    # Extract Environment (Breadcrumbs, Tags, etc.)
    environment = {}
    if "tags" in payload:
        environment["tags"] = payload["tags"]
    if "breadcrumbs" in payload:
        environment["breadcrumbs"] = payload["breadcrumbs"]
    if "contexts" in payload:
        environment["contexts"] = payload["contexts"]
        
    return BugFinding(
        id=str(event_id),
        title=title,
        description=description,
        stack_trace=stack_trace,
        files_hint=list(files_hint),
        environment=environment
    )

def parse_github_issue(issue: Dict[str, Any]) -> BugFinding:
    """
    Parses a GitHub Issue JSON payload into a normalized BugFinding.
    Extracts stack traces from markdown code blocks.
    """
    issue_id = str(issue.get("number") or issue.get("id") or "unknown-github-id")
    title = issue.get("title", "GitHub Issue")
    body = issue.get("body") or ""
    
    # Simple regex to find python/JS/generic stack traces in markdown code blocks
    stack_trace = None
    stack_match = re.search(r"```[a-zA-Z]*\n(Traceback.*?|.*?Error:.*?)\n```", body, re.DOTALL)
    if stack_match:
        stack_trace = stack_match.group(1).strip()
    else:
        # Check generic code block if it looks like a stack trace
        generic_match = re.search(r"```\n(.*?(?:File \".*?\", line \d+|Error:|Exception).*?)\n```", body, re.DOTALL)
        if generic_match:
            stack_trace = generic_match.group(1).strip()
            
    # Extract file hints from body text or stack trace
    files_hint = set()
    if stack_trace:
        # e.g., File "src/main.py", line 10
        file_matches = re.findall(r'File "([^"]+)"', stack_trace)
        files_hint.update(file_matches)
        
    environment = {
        "labels": [label.get("name") for label in issue.get("labels", []) if isinstance(label, dict)],
        "state": issue.get("state"),
        "url": issue.get("html_url")
    }
    
    return BugFinding(
        id=issue_id,
        title=title,
        description=body,
        stack_trace=stack_trace,
        files_hint=list(files_hint),
        environment=environment
    )

def parse_freeform_text(text: str) -> BugFinding:
    """
    Uses OpenAI's structured outputs to parse freeform text into a BugFinding.
    """
    client = openai.OpenAI()
    
    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are an expert bug triage agent. Extract the bug report details into the structured BugFinding schema as a JSON object. The JSON must have these keys: id, title, description, stack_trace (string or null), files_hint (list of strings), environment (object). Preserve exact line numbers, file paths, and stack traces. If no ID is provided, generate a descriptive string ID."},
            {"role": "user", "content": text}
        ],
        response_format={"type": "json_object"},
        temperature=0.0
    )
    
    parsed_json = json.loads(completion.choices[0].message.content)
    return BugFinding(**parsed_json)
