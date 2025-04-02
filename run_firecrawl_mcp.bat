@echo off
REM 设置环境变量
set FIRECRAWL_API_KEY=fc-952fa073ed8b421cbc982d896ad51da2

REM 执行命令
set FIRECRAWL_API_KEY=fc-952fa073ed8b421cbc982d896ad51da2 & npx -y supergateway --stdio "npx -y firecrawl-mcp" --port 8000 --baseUrl http://localhost:8000 --ssePath /sse --messagePath /message

REM 如果需要保持窗口打开，可以添加以下命令
pause
