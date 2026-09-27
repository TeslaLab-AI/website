import os
import re
import subprocess
from typing import List, Dict, Any, Optional

try:
    import tiktoken
except ImportError:
    tiktoken = None

from tree_sitter import Parser, Language, Query, QueryCursor
import tree_sitter_python as tspython
import tree_sitter_javascript as tsjavascript

from app.contracts.schemas import EvidencePack, CodeChunk, ContextPack
from app.tools.security import tool_telemetry

import tree_sitter_typescript as tstypescript

# Supported languages for AST
LANGUAGES = {
    'python': Language(tspython.language()),
    'javascript': Language(tsjavascript.language()),
    'typescript': Language(tstypescript.language_typescript()),
}

MAX_TOKEN_BUDGET = 4000

def _get_language_from_ext(file_path: str) -> Optional[str]:
    ext = os.path.splitext(file_path)[1].lower()
    if ext == '.py': return 'python'
    if ext in ('.js', '.jsx'): return 'javascript'
    if ext in ('.ts', '.tsx'): return 'typescript'
    return None

def _count_tokens(text: str) -> int:
    """Uses tiktoken to count tokens if available, otherwise fallback heuristic."""
    if tiktoken:
        try:
            encoding = tiktoken.get_encoding("cl100k_base")
            return len(encoding.encode(text, disallowed_special=()))
        except Exception:
            pass
    # Fallback heuristic: ~4 chars per token
    return len(text) // 4

def _get_git_recency_score(file_path: str, workspace_path: str) -> float:
    """Returns 0.4 if edited in the last 7 days, else 0.0"""
    try:
        res = subprocess.run(
            ["git", "log", "-1", '--format=%ct', "--", file_path],
            cwd=workspace_path,
            capture_output=True,
            text=True
        )
        if res.stdout.strip():
            import time
            commit_time = int(res.stdout.strip())
            if time.time() - commit_time < 7 * 86400:
                return 0.4
    except Exception:
        pass
    return 0.0

def score_files(evidence: EvidencePack, workspace_path: str) -> Dict[str, float]:
    """
    Ranks candidate files by relevance based on stack trace/files_hint (1.0),
    direct imports (0.7 - simplified heuristic), and git recency (0.4).
    """
    scores: Dict[str, float] = {}
    
    # 1. Stack trace / Hint matching (1.0)
    implicated_files = set()
    
    if evidence.stack_trace:
        # Match any plausible file path in the stack trace
        paths = re.findall(r'([a-zA-Z0-9_/\-\.]+\.(?:ts|json|js|py))', evidence.stack_trace)
        for p in paths:
            # Normalize to relative path
            rel_p = p.replace('\\', '/')
            if rel_p.startswith(workspace_path.replace('\\', '/')):
                rel_p = rel_p[len(workspace_path):].lstrip('/')
            implicated_files.add(rel_p)

    for f in implicated_files:
        scores[f] = scores.get(f, 0.0) + 1.0

    # Apply Git Recency
    for f in list(scores.keys()):
        scores[f] += _get_git_recency_score(f, workspace_path)
        
    return scores

def extract_ast_chunks(file_path: str, workspace_path: str, base_score: float) -> List[CodeChunk]:
    """Parses a file and extracts function/class blocks to maximize token density."""
    abs_path = os.path.join(workspace_path, file_path)
    if not os.path.exists(abs_path):
        return []
        
    try:
        with open(abs_path, 'rb') as f:
            src = f.read()
    except Exception:
        return []
        
    lang_str = _get_language_from_ext(file_path)
    
    # If not a supported AST language (e.g., json, yaml), chunk by entire file or just return the file
    if not lang_str:
        try:
            content = src.decode('utf-8')
            lines = content.splitlines()
            return [CodeChunk(
                file_path=file_path,
                content=content,
                start_line=1,
                end_line=len(lines),
                relevance_score=base_score
            )]
        except Exception:
            return []

    lang = LANGUAGES.get(lang_str)
    if not lang: return []

    parser = Parser(lang)
    tree = parser.parse(src)
    
    # Extract functions and classes
    if lang_str == 'python':
        q_str = """
        (function_definition name: (identifier) @name) @def
        (class_definition name: (identifier) @name) @def
        """
    else: # JS/TS
        q_str = """
        (function_declaration) @def
        (class_declaration) @def
        (method_definition) @def
        """
        
    query = Query(lang, q_str)
    cursor = QueryCursor(query)
    captures_dict = cursor.captures(tree.root_node)
    
    chunks = []
    
    # captures_dict has keys "name" and "def"
    # To match names with defs, we can iterate over the defs and find their name children
    # For simplicity, we just extract the def node block
    def_nodes = captures_dict.get("def", [])
    
    for node in def_nodes:
        # Get function name (first named child that is an identifier)
        func_name = "unknown_block"
        for child in node.children:
            if child.type in ('identifier', 'property_identifier', 'type_identifier'):
                func_name = src[child.start_byte:child.end_byte].decode("utf-8")
                break
                
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        content = src[node.start_byte:node.end_byte].decode("utf-8")
        
        chunks.append(CodeChunk(
            file_path=file_path,
            function_name=func_name,
            content=content,
            start_line=start_line,
            end_line=end_line,
            relevance_score=base_score # inherit file relevance
        ))
        
    # If no functions/classes found, or it's a small script, maybe return whole file
    if not chunks:
        content = src.decode('utf-8')
        chunks.append(CodeChunk(
            file_path=file_path,
            content=content,
            start_line=1,
            end_line=len(content.splitlines()),
            relevance_score=base_score
        ))
        
    return chunks

@tool_telemetry
def build_context_pack(evidence: EvidencePack, workspace_path: str) -> ContextPack:
    """
    Build greedy packing algorithm to pack chunks up to strict 4,000 token limit.
    """
    file_scores = score_files(evidence, workspace_path)
    
    all_chunks = []
    for fp, score in file_scores.items():
        all_chunks.extend(extract_ast_chunks(fp, workspace_path, score))
        
    # Sort chunks by relevance score descending
    # As a tie breaker, maybe chunk size, or prioritize chunks that encompass lines mentioned in stack trace
    # To be extremely precise, if a chunk encompasses a line from stack trace, we give it a huge boost
    for chunk in all_chunks:
        if evidence.stack_trace and chunk.file_path in evidence.stack_trace:
            # Check if stack trace has line number
            lines = re.findall(rf'{re.escape(chunk.file_path)}[\'"]?,? line (\d+)', evidence.stack_trace)
            lines += re.findall(rf'{re.escape(chunk.file_path)}:(\d+):', evidence.stack_trace)
            for l in lines:
                if chunk.start_line <= int(l) <= chunk.end_line:
                    chunk.relevance_score += 5.0 # Massive boost for encompassing the crash line!
                    
    # Sort
    all_chunks.sort(key=lambda c: c.relevance_score, reverse=True)
    
    packed_chunks = []
    current_tokens = 0
    
    for chunk in all_chunks:
        # chunk formatting overhead
        chunk_text = f"File: {chunk.file_path}\nLines: {chunk.start_line}-{chunk.end_line}\n```{chunk.content}```\n\n"
        tokens = _count_tokens(chunk_text)
        
        if current_tokens + tokens <= MAX_TOKEN_BUDGET:
            packed_chunks.append(chunk)
            current_tokens += tokens
            
    return ContextPack(
        chunks=packed_chunks,
        total_tokens=current_tokens
    )
