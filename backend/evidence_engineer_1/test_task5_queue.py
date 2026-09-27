import asyncio
import httpx
import time
import json

async def trigger_investigation(client, finding_id):
    start_time = time.time()
    response = await client.post(f"http://localhost:8000/api/findings/{finding_id}/investigate")
    latency = time.time() - start_time
    assert response.status_code == 202, f"Expected 202, got {response.status_code}: {response.text}"
    data = response.json()
    celery_task_id = data["celery_task_id"]
    return celery_task_id, latency

async def poll_task(client, celery_task_id):
    for _ in range(20): # Max 20 seconds polling
        response = await client.get(f"http://localhost:8000/api/tasks/status/{celery_task_id}")
        data = response.json()
        if data["status"] == "SUCCESS":
            return True
        elif data["status"] == "FAILURE":
            return False
        await asyncio.sleep(1)
    return False

async def main():
    print("Testing 5 concurrent background tasks...")
    finding_ids = ["FINDING-BUG-001", "FINDING-BUG-002", "FINDING-BUG-003", "FINDING-DEP-001", "FINDING-SEC-001"]
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        # 1. Trigger all 5 concurrently
        trigger_tasks = [trigger_investigation(client, fid) for fid in finding_ids]
        results = await asyncio.gather(*trigger_tasks)
        
        celery_task_ids = []
        for i, (task_id, latency) in enumerate(results):
            # Verify constraint
            assert latency < 5.0, f"Latency {latency} exceeded 5.0s constraint!"
            celery_task_ids.append(task_id)
            
        print("\n[SUCCESS] All tasks triggered within constraint. 202 Accepted returned.")
        print("Polling Celery worker for completion...")
        
        # 2. Poll for completion
        poll_tasks = [poll_task(client, tid) for tid in celery_task_ids]
        poll_results = await asyncio.gather(*poll_tasks)
        
        for i, success in enumerate(poll_results):
            status = "SUCCESS" if success else "FAILED / TIMEOUT"
            print(f"Worker Job {i+1}: {status}")
            
        if all(poll_results):
            print("\nTest Passed: Async Worker execution verified!")
        else:
            print("\nTest Failed: Not all tasks completed successfully.")

if __name__ == "__main__":
    asyncio.run(main())
