"""Test script for the FireCrawl API service."""
import asyncio
import sys
import os
import json

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import aiohttp
from app.tool.firecrawl_api import start_server


async def test_firecrawl_api():
    """Test the FireCrawl API with a simple example."""
    # Create a session
    async with aiohttp.ClientSession() as session:
        # Test health check
        async with session.get("http://localhost:8080/health") as response:
            print(f"Health check status: {response.status}")
            print(await response.json())
        
        # Test crawling example.com
        payload = {
            "url": "https://example.com",
            "depth": 0,
            "max_pages": 1,
            "timeout": 30,
            "extract_content": True,
            "follow_external_links": False
        }
        
        async with session.post("http://localhost:8080/crawl", json=payload) as response:
            print(f"\nCrawl status: {response.status}")
            result = await response.json()
            print(json.dumps(result, indent=2))
        
        # Test crawling python.org with depth
        payload = {
            "url": "https://www.python.org",
            "depth": 1,
            "max_pages": 3,
            "timeout": 30,
            "extract_content": True,
            "follow_external_links": False
        }
        
        async with session.post("http://localhost:8080/crawl", json=payload) as response:
            print(f"\nCrawl status: {response.status}")
            result = await response.json()
            # Print just the summary to avoid too much output
            print(f"Status: {result['status']}")
            print(f"Message: {result['message']}")
            print(f"Total pages: {result['total_pages']}")
            print(f"Number of results: {len(result['results'])}")
            
            # Print titles of crawled pages
            for i, page in enumerate(result['results']):
                print(f"Page {i+1}: {page['url']} - {page['title']}")


if __name__ == "__main__":
    print("Testing FireCrawl API...")
    print("Make sure the API server is running on http://localhost:8080")
    print("You can start it with: python run_firecrawl_api.py")
    
    asyncio.run(test_firecrawl_api())
