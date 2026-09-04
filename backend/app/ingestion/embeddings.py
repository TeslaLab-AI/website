"""
Purpose:
Handles the generation of embeddings using the OpenAI API.
"""
import os
import openai
from tenacity import retry, wait_random_exponential, stop_after_attempt

# Setup OpenAI client. Ensure OPENAI_API_KEY is in the environment
client = openai.OpenAI()

@retry(wait=wait_random_exponential(min=1, max=60), stop=stop_after_attempt(6))
def _generate_batch(texts: list[str]) -> list[list[float]]:
    response = client.embeddings.create(
        input=texts,
        model="text-embedding-3-small"
    )
    return [data.embedding for data in response.data]

def generate_embeddings(texts: list[str]) -> list[list[float]]:
    """
    Calls the OpenAI API to generate embeddings for a list of strings in batches.
    """
    if not texts:
        return []
        
    # Replace empty strings to avoid OpenAI BadRequestError for empty inputs
    safe_texts = [t if t.strip() else "empty_chunk" for t in texts]
    
    all_embeddings = []
    batch_size = 100
    
    for i in range(0, len(safe_texts), batch_size):
        batch = safe_texts[i:i+batch_size]
        all_embeddings.extend(_generate_batch(batch))
        
    return all_embeddings
