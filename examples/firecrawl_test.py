"""Test script for the FireCrawl tool."""
import asyncio
import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.tool.firecrawl import FireCrawl


async def test_firecrawl():
    """Test the FireCrawl tool with a simple example."""
    crawler = FireCrawl()
    
    # Test with a simple website
    print("Testing FireCrawl with example.com...")
    result = await crawler.execute(url="https://example.com")
    print(result)
    
    # Test with a more complex website and follow links
    print("\nTesting FireCrawl with depth=1 on python.org...")
    result = await crawler.execute(
        url="https://www.python.org",
        depth=1,
        max_pages=3,
        extract_content=True
    )
    print(result)


if __name__ == "__main__":
    asyncio.run(test_firecrawl())
