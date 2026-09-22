import os
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional

from tree_sitter import Language, Parser
import tree_sitter_python as tspython
import tree_sitter_javascript as tsjavascript

from .security import repo_sandbox, tool_telemetry

# Supported languages
LANGUAGES = {
    'python': Language(tspython.language()),
    'javascript': Language(tsjavascript.language()),
    'typescript': Language(tsjavascript.language()),
}

@tool_telemetry
@repo_sandbox
def find_files_by_name(pattern: str, workspace_path: str) -> List[str]:
    """Finds files in the workspace matching the glob pattern."""
    import fnmatch
    matches = []
    # Use os.walk to aggressively prune ignored directories (lightning fast)
    for root, dirs, files in os.walk(workspace_path):
        dirs[:] = [d for d in dirs if d not in ('.git', 'venv', 'node_modules', '__pycache__', '.pytest_cache')]
        for file in files:
            if fnmatch.fnmatch(file, pattern):
                matches.append(os.path.relpath(os.path.join(root, file), workspace_path))
    return matches

@tool_telemetry
@repo_sandbox
def search_code(regex: str, workspace_path: str) -> str:
    """
    Searches the workspace for the given regex using ripgrep (`rg`).
    Falls back to `git grep` and then native Python search if `rg` isn't installed.
    """
    try:
        result = subprocess.run(
            ["rg", "-n", regex],
            cwd=workspace_path,
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout
    except FileNotFoundError:
        pass # rg not installed
    except subprocess.CalledProcessError as e:
        return e.stdout if e.stdout else "No matches found."

    try:
        result = subprocess.run(
            ["git", "grep", "--untracked", "-n", "-E", regex],
            cwd=workspace_path,
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout
    except FileNotFoundError:
        pass
    except subprocess.CalledProcessError as e:
        pass # continue to fallback if git grep fails (e.g. not a git repo or no matches in tracked/untracked)
        
    import re
    matches = []
    prog = re.compile(regex)
    abs_workspace = os.path.abspath(workspace_path)
    
    for root, dirs, files in os.walk(workspace_path):
        dirs[:] = [d for d in dirs if d not in ('.git', 'venv', 'node_modules', '__pycache__', '.pytest_cache')]
        for file in files:
            p = os.path.join(root, file)
            try:
                with open(p, "r", encoding="utf-8") as f:
                    for i, line in enumerate(f):
                        if prog.search(line):
                            rel_path = os.path.relpath(p, workspace_path)
                            matches.append(f"{rel_path}:{i+1}:{line.strip()}")
            except UnicodeDecodeError:
                pass
                
    return "\n".join(matches) if matches else "No matches found."

@tool_telemetry
@repo_sandbox
def read_file_chunk(path: str, start_line: int, end_line: int, workspace_path: str) -> str:
    """Reads lines from start_line to end_line (1-indexed, inclusive)."""
    abs_path = os.path.abspath(os.path.join(workspace_path, path))
    if not os.path.isfile(abs_path):
        return f"File not found: {path}"
        
    try:
        with open(abs_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
        start_idx = max(0, start_line - 1)
        end_idx = min(len(lines), end_line)
        return "".join(lines[start_idx:end_idx])
    except Exception as e:
        return f"Error reading file: {str(e)}"

def _parse_file(abs_path: str, language_str: str):
    lang = LANGUAGES.get(language_str.lower())
    if not lang:
        raise ValueError(f"Unsupported language: {language_str}")
        
    parser = Parser(lang)
    with open(abs_path, "rb") as f:
        src = f.read()
    tree = parser.parse(src)
    return lang, src, tree

@tool_telemetry
@repo_sandbox
def get_symbol_definition(path: str, symbol: str, language: str, workspace_path: str) -> str:
    """Uses tree-sitter to find a class/function definition of the given symbol in the file."""
    abs_path = os.path.abspath(os.path.join(workspace_path, path))
    try:
        lang, src, tree = _parse_file(abs_path, language)
        if language.lower() == 'python':
            q_str = f"""
            (function_definition name: (identifier) @name (#eq? @name "{symbol}")) @def
            (class_definition name: (identifier) @name (#eq? @name "{symbol}")) @def
            """
        else:
            q_str = f"""
            (function_declaration name: (identifier) @name (#eq? @name "{symbol}")) @def
            (class_declaration name: [(identifier) (type_identifier)] @name (#eq? @name "{symbol}")) @def
            (method_definition name: (property_identifier) @name (#eq? @name "{symbol}")) @def
            """
            
        from tree_sitter import Query, QueryCursor
        query = Query(lang, q_str)
        cursor = QueryCursor(query)
        captures_dict = cursor.captures(tree.root_node)
        
        defs = []
        for node in captures_dict.get("def", []):
            defs.append(src[node.start_byte:node.end_byte].decode("utf-8"))
                
        return "\n\n".join(defs) if defs else f"Definition of {symbol} not found in {path}"
    except Exception as e:
        return f"Error parsing definition: {str(e)}"

@tool_telemetry
@repo_sandbox
def find_references(path: str, symbol: str, language: str, workspace_path: str) -> str:
    """Uses tree-sitter to find usages of a symbol in the specified file."""
    abs_path = os.path.abspath(os.path.join(workspace_path, path))
    try:
        lang, src, tree = _parse_file(abs_path, language)
        q_str = f"""
        ((identifier) @id (#eq? @id "{symbol}"))
        """
        
        from tree_sitter import Query, QueryCursor
        query = Query(lang, q_str)
        cursor = QueryCursor(query)
        captures_dict = cursor.captures(tree.root_node)
        
        refs = []
        for node in captures_dict.get("id", []):
            line_no = node.start_point[0] + 1
            line_start = src.rfind(b'\\n', 0, node.start_byte)
            line_start = line_start + 1 if line_start != -1 else 0
            
            line_end = src.find(b'\\n', node.end_byte)
            if line_end == -1: line_end = len(src)
            line_text = src[line_start:line_end].decode("utf-8").strip()
            
            refs.append(f"Line {line_no}: {line_text}")
            
        return "\n".join(refs) if refs else f"No references to {symbol} found in {path}"
    except Exception as e:
        return f"Error parsing references: {str(e)}"
