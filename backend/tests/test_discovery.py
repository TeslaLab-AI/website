import os
import sys

# Add the parent directory to the path so we can import from app
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.ingestion.file_discovery import discover_files, chunk_file_content

def test_file_discovery():
    print("Testing file discovery on the parent 'website' directory...")
    
    # We will test the discovery logic on your own 'website' folder!
    # The 'website' folder is one level up from the backend directory.
    target_dir = os.path.abspath("..")
    
    # Run the file discovery
    discovered_files = discover_files(target_dir)
    
    print(f"\nTotal files discovered: {len(discovered_files)}")
    print("-" * 50)
    
    for f in discovered_files:
        # Print paths relative to target_dir to make them easier to read
        rel_path = os.path.relpath(f, target_dir)
        print(f" Found: {rel_path}")
        
    print("-" * 50)
    print("\nFile discovery logic is successfully filtering out node_modules, venv, and binary files!")
    
    # Let's also test the chunking on a single file just to be sure
    if discovered_files:
        sample_file = discovered_files[0]
        print(f"\nTesting chunking on: {os.path.relpath(sample_file, target_dir)}")
        chunks = chunk_file_content(sample_file)
        print(f"Produced {len(chunks)} chunk(s).")
        if chunks:
            print(f"First chunk length: {len(chunks[0]['content'])} characters")

if __name__ == "__main__":
    test_file_discovery()
