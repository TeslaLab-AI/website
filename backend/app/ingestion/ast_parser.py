"""
Purpose:
Provides AST-based semantic chunking using Tree-sitter.

Responsibilities:
- Parse supported source files (Python, JS, TS) into an AST.
- Extract high-level structural nodes (functions, classes) as semantic chunks.
"""

import tree_sitter
import tree_sitter_python
import tree_sitter_javascript
import tree_sitter_typescript

# Initialize Language objects
LANG_PYTHON = tree_sitter.Language(tree_sitter_python.language())
LANG_JS = tree_sitter.Language(tree_sitter_javascript.language())
LANG_TS = tree_sitter.Language(tree_sitter_typescript.language_typescript())
LANG_TSX = tree_sitter.Language(tree_sitter_typescript.language_tsx())

LANGUAGE_MAP = {
    "py": LANG_PYTHON,
    "js": LANG_JS,
    "jsx": LANG_JS,
    "ts": LANG_TS,
    "tsx": LANG_TSX
}

# Node types that represent meaningful standalone semantic chunks
CHUNK_NODE_TYPES = {
    # Python
    "function_definition",
    "class_definition",
    # JS/TS
    "function_declaration",
    "class_declaration",
    "method_definition"
}

def parse_file_ast(content: str, ext: str) -> list[str]:
    """
    Parses the file content into an AST and extracts semantic chunks (functions/classes).
    Returns a list of extracted chunk strings.
    """
    ext = ext.lstrip('.').lower()
    if ext not in LANGUAGE_MAP:
        return []

    try:
        parser = tree_sitter.Parser(LANGUAGE_MAP[ext])
    except TypeError:
        # Compatibility for different tree-sitter versions
        parser = tree_sitter.Parser()
        parser.set_language(LANGUAGE_MAP[ext])

    content_bytes = content.encode('utf-8')
    tree = parser.parse(content_bytes)

    chunks = []
    
    # We use a simple recursive traversal to find target nodes
    def traverse(node):
        # Extract if it matches our target semantic structures
        if node.type in CHUNK_NODE_TYPES:
            chunk_bytes = content_bytes[node.start_byte:node.end_byte]
            chunks.append(chunk_bytes.decode('utf-8'))
            
            # Note: We do NOT traverse children if we extract the parent class/function,
            # to avoid duplicating code (e.g. methods inside a class are already in the class chunk).
            # However, if a class is HUGE, it might exceed token limits.
            # For Phase 3 MVP, grabbing the whole class/function is sufficient.
            return
            
        for child in node.children:
            traverse(child)

    traverse(tree.root_node)
    
    return chunks
