from contextlib import AsyncExitStack
from typing import List, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.types import TextContent
npx -y supergateway \
    --stdio "npx -y firecrawl-mcp" \
    --port 8000 --baseUrl http://localhost:8000 \
    --ssePath /sse --messagePath /message \
    --env FIRECRAWL_API_KEY=fc-952fa073ed8b421cbc982d896ad51da2


