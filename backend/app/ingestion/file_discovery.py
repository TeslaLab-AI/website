"""
Purpose:
Discovers and filters files in a downloaded repository for analysis.

Responsibilities:
- Traverse the repository directory tree.
- Parse and respect .gitignore rules.
- Filter out binary files and unsupported extensions.
"""

import os
from pathlib import Path
import pathspec

# Extensions to process for semantic search and code intelligence
SUPPORTED_EXTENSIONS = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".c", ".cpp", ".h", 
    ".java", ".cs", ".rb", ".php", ".html", ".css", ".sql", ".md", ".json", 
    ".yaml", ".yml", ".toml", ".sh"
}

def discover_files(repo_root: str) -> list[str]:
    """
    Walks the repository root, respecting .gitignore, and returns a list of 
    absolute file paths that should be processed.
    """
    gitignore_path = os.path.join(repo_root, ".gitignore")
    
    # Base spec ignores .git directory and common binaries
    lines = [".git/", "node_modules/", "venv/", "__pycache__/", "*.pyc"]
    
    if os.path.exists(gitignore_path):
        with open(gitignore_path, "r", encoding="utf-8") as f:
            lines.extend(f.readlines())
            
    spec = pathspec.PathSpec.from_lines(pathspec.patterns.GitWildMatchPattern, lines)
    
    files_to_process = []
    repo_path = Path(repo_root)
    
    for file_path in repo_path.rglob("*"):
        if not file_path.is_file():
            continue
            
        # Get path relative to repo root for gitignore matching
        rel_path = str(file_path.relative_to(repo_path))
        
        # Skip if matches .gitignore
        if spec.match_file(rel_path):
            continue
            
        # Skip if not supported extension
        if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
            
        files_to_process.append(str(file_path))
        
    return files_to_process

def chunk_file_content(file_path: str, max_tokens: int = 1500) -> list[dict]:
    """
    Reads a file and splits it into semantic chunks.
    (Simple line-based chunking for now. Tree-sitter can be integrated later).
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError:
        return [] # Skip binary or weirdly encoded files
        
    ext = Path(file_path).suffix
    
    # Try AST chunking first for supported languages
    from app.ingestion.ast_parser import parse_file_ast
    ast_chunks = parse_file_ast(content, ext)
    
    if ast_chunks:
        print(f"AST Parser: Extracted {len(ast_chunks)} semantic chunks from {Path(file_path).name}")
        chunks = []
        for chunk_text in ast_chunks:
            chunks.append({
                "content": chunk_text,
                "language": ext.lstrip('.')
            })
        return chunks
        
    # Fallback naive chunking (character based) for Phase 1 or unsupported languages
    # ~4 chars per token, so 1500 tokens = ~6000 chars
    CHUNK_SIZE = 6000
    OVERLAP = 500
    
    chunks = []
    start = 0
    while start < len(content):
        end = start + CHUNK_SIZE
        chunk_text = content[start:end]
        chunks.append({
            "content": chunk_text,
            "language": Path(file_path).suffix.lstrip('.')
        })
        start += (CHUNK_SIZE - OVERLAP)
        
    return chunks
