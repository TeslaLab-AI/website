import os
import sys
import time
import logging
from functools import wraps

logger = logging.getLogger(__name__)

class SecurityException(Exception):
    """Raised when an operation attempts to breach the repository sandbox."""
    pass

def repo_sandbox(func):
    """
    Decorator to enforce path traversal jail.
    Requires `workspace_path` and `path` to be passed as kwargs or handles the first arg.
    It resolves the absolute path and checks if it starts with the absolute workspace path.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Extract workspace_path and path from args/kwargs
        workspace_path = kwargs.get('workspace_path')
        if not workspace_path and len(args) > 1:
            workspace_path = args[1] if func.__name__ != 'read_file_chunk' else args[3]
            
        path = kwargs.get('path')
        if not path and args:
            path = args[0]
            
        # For find_files_by_name and search_code, path is not a file, it's a regex/pattern
        if func.__name__ in ('find_files_by_name', 'search_code'):
            return func(*args, **kwargs)

        if workspace_path and path:
            abs_workspace = os.path.abspath(workspace_path)
            # Normalizing path against workspace
            abs_path = os.path.abspath(os.path.join(abs_workspace, path))
            
            if not abs_path.startswith(abs_workspace):
                raise SecurityException(f"Path traversal blocked: {path} escapes {workspace_path}")
        
        return func(*args, **kwargs)
    return wrapper

def tool_telemetry(func):
    """
    Decorator to log telemetry of tool execution: duration, arguments, and result size.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        
        try:
            result = func(*args, **kwargs)
            duration_ms = (time.time() - start_time) * 1000
            
            # Estimate byte size
            if isinstance(result, str):
                size_bytes = len(result.encode('utf-8'))
            elif isinstance(result, list):
                size_bytes = sum(len(str(item).encode('utf-8')) for item in result)
            else:
                size_bytes = sys.getsizeof(result)

            logger.info(
                f"[TELEMETRY] Tool: {func.__name__} | "
                f"Duration: {duration_ms:.2f}ms | "
                f"Result Size: {size_bytes} bytes"
            )
            return result
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            logger.error(
                f"[TELEMETRY] Tool: {func.__name__} | "
                f"Duration: {duration_ms:.2f}ms | "
                f"Error: {str(e)}"
            )
            raise
    return wrapper
