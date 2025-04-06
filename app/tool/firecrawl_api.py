"""FireCrawl API service for web crawling and data extraction."""
import asyncio
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import uvicorn

from app.logger import logger


class CrawlRequest(BaseModel):
    """Request parameters for crawl operation."""
    url: str = Field(description="The URL to crawl")
    depth: int = Field(default=0, description="How many levels of links to follow")
    max_pages: int = Field(default=5, description="Maximum number of pages to crawl")
    timeout: int = Field(default=30, description="Timeout in seconds for each request")
    extract_content: bool = Field(default=True, description="Whether to extract page content")
    follow_external_links: bool = Field(default=False, description="Whether to follow external links")


class CrawlResult(BaseModel):
    """Result of a crawl operation."""
    url: str = Field(description="The URL that was crawled")
    title: Optional[str] = Field(default=None, description="Page title")
    content: Optional[str] = Field(default=None, description="Extracted text content")
    links: List[str] = Field(default_factory=list, description="Links found on the page")
    status: str = Field(description="Status of the crawl operation")


class CrawlResponse(BaseModel):
    """API response for crawl operation."""
    results: List[CrawlResult] = Field(default_factory=list, description="Crawl results")
    total_pages: int = Field(description="Total number of pages crawled")
    status: str = Field(description="Overall status of the operation")
    message: str = Field(description="Status message")


class FireCrawlService:
    """Service for web crawling and data extraction."""
    
    # Store crawled URLs to avoid duplicates
    _visited_urls: Dict[str, CrawlResult] = {}
    _session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
                }
            )
        return self._session

    async def _close_session(self) -> None:
        """Close the aiohttp session if it exists."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    def _is_same_domain(self, url1: str, url2: str) -> bool:
        """Check if two URLs belong to the same domain."""
        domain1 = urlparse(url1).netloc
        domain2 = urlparse(url2).netloc
        return domain1 == domain2

    async def _crawl_page(
        self, url: str, extract_content: bool = True, timeout: int = 30
    ) -> CrawlResult:
        """Crawl a single page and extract data."""
        # Check if already visited
        if url in self._visited_urls:
            return self._visited_urls[url]

        try:
            session = await self._get_session()
            async with session.get(url, timeout=timeout) as response:
                if response.status != 200:
                    return CrawlResult(
                        url=url,
                        status=f"Error: HTTP {response.status}",
                    )

                html = await response.text()
                soup = BeautifulSoup(html, "html.parser")

                # Extract title
                title = soup.title.text.strip() if soup.title else None

                # Extract content if requested
                content = None
                if extract_content:
                    # Remove script and style elements
                    for script in soup(["script", "style", "header", "footer", "nav"]):
                        script.extract()
                    
                    # Get text content
                    content = soup.get_text(separator="\n", strip=True)
                    # Limit content size to avoid excessive output
                    content = content[:10000] if content else None

                # Extract links
                links = []
                for link in soup.find_all("a", href=True):
                    href = link["href"]
                    # Convert relative URLs to absolute
                    if not href.startswith(("http://", "https://")):
                        href = urljoin(url, href)
                    links.append(href)

                result = CrawlResult(
                    url=url,
                    title=title,
                    content=content,
                    links=links,
                    status="Success",
                )
                
                # Store in visited URLs
                self._visited_urls[url] = result
                return result

        except asyncio.TimeoutError:
            return CrawlResult(
                url=url,
                status="Error: Request timed out",
            )
        except Exception as e:
            logger.error(f"Error crawling {url}: {str(e)}")
            return CrawlResult(
                url=url,
                status=f"Error: {str(e)}",
            )

    async def crawl(self, request: CrawlRequest) -> CrawlResponse:
        """
        Crawl web pages based on the request parameters.
        
        Args:
            request: The crawl request parameters
            
        Returns:
            CrawlResponse containing the crawl results
        """
        # Reset visited URLs for new execution
        self._visited_urls = {}
        
        # Validate URL
        if not request.url.startswith(("http://", "https://")):
            return CrawlResponse(
                results=[],
                total_pages=0,
                status="Error",
                message=f"Invalid URL: {request.url}. URL must start with http:// or https://"
            )

        # Start with the initial URL
        to_visit = [(request.url, 0)]  # (url, current_depth)
        results = []

        try:
            while to_visit and len(results) < request.max_pages:
                current_url, current_depth = to_visit.pop(0)
                
                # Skip if already visited
                if current_url in self._visited_urls:
                    continue
                
                # Crawl the page
                result = await self._crawl_page(
                    current_url, 
                    extract_content=request.extract_content,
                    timeout=request.timeout
                )
                results.append(result)
                
                # Add links to visit if we haven't reached max depth
                if current_depth < request.depth:
                    for link in result.links:
                        # Skip if already visited or in queue
                        if link in self._visited_urls or any(link == u for u, _ in to_visit):
                            continue
                            
                        # Check if we should follow external links
                        if not request.follow_external_links and not self._is_same_domain(request.url, link):
                            continue
                            
                        to_visit.append((link, current_depth + 1))
            
            return CrawlResponse(
                results=results,
                total_pages=len(results),
                status="Success",
                message=f"Crawled {len(results)} pages starting from {request.url}"
            )
            
        except Exception as e:
            logger.error(f"Error in FireCrawl: {str(e)}")
            return CrawlResponse(
                results=[],
                total_pages=0,
                status="Error",
                message=f"Error executing FireCrawl: {str(e)}"
            )
        finally:
            # Clean up resources
            await self._close_session()


# Create FastAPI app
app = FastAPI(
    title="FireCrawl API",
    description="Web crawling and data extraction API",
    version="1.0.0",
)

# Create service instance
service = FireCrawlService()


@app.post("/crawl", response_model=CrawlResponse)
async def crawl(request: CrawlRequest):
    """
    Crawl web pages based on the request parameters.
    """
    try:
        return await service.crawl(request)
    except Exception as e:
        logger.error(f"Error processing crawl request: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


def start_server(host: str = "0.0.0.0", port: int = 8080):
    """Start the FireCrawl API server."""
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    start_server()
