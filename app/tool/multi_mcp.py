"""支持多个MCP服务器连接的工具集合。"""

from typing import Any, Dict, List, Optional, Tuple

from app.logger import logger
from app.tool.base import ToolResult
from app.tool.mcp import MCPClients
from app.tool.tool_collection import ToolCollection


class MultiMCPClients(ToolCollection):
    """管理多个MCP客户端连接的工具集合。

    这个类允许同时连接到多个MCP服务器，并将它们的工具统一到一个接口中。
    每个工具名称前会添加服务器名称作为前缀，以避免名称冲突。
    """

    def __init__(self):
        super().__init__()  # 初始化空工具列表
        self.clients: Dict[str, MCPClients] = {}  # 存储多个MCPClients实例
        self.name = "multi_mcp"
        self.description = "Multiple MCP client tools for server interaction"

    async def add_client(
        self,
        name: str,
        connection_type: str,
        server_url: Optional[str] = None,
        command: Optional[str] = None,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> MCPClients:
        """添加一个新的MCP客户端。

        Args:
            name: 客户端的唯一名称
            connection_type: 连接类型 ("stdio" 或 "sse")
            server_url: SSE连接的服务器URL
            command: stdio连接的命令
            args: 命令的参数
            env: 环境变量

        Returns:
            新添加的MCPClients实例
        """
        # 创建新的MCPClients实例
        client = MCPClients()

        # 连接到MCP服务器
        if connection_type == "sse":
            if not server_url:
                raise ValueError(f"Server URL is required for SSE connection: {name}")
            await client.connect_sse(server_url=server_url)
        elif connection_type == "stdio":
            if not command:
                raise ValueError(f"Command is required for stdio connection: {name}")
            await client.connect_stdio(command=command, args=args or [], env=env)
        else:
            raise ValueError(f"Unsupported connection type: {connection_type}")

        # 存储客户端实例
        self.clients[name] = client

        # 更新工具映射
        await self._update_tool_map()

        return client

    async def _update_tool_map(self) -> None:
        """更新统一的工具映射。"""
        # 清除现有工具
        self.tool_map = {}
        all_tools = []

        # 遍历所有客户端
        for client_name, client in self.clients.items():
            if not client.session:
                continue

            # 为每个客户端的工具添加前缀
            for tool_name, tool in client.tool_map.items():
                # 使用客户端名称作为前缀，避免名称冲突
                prefixed_name = f"{client_name}.{tool_name}"

                # 创建一个代理工具，保持原始工具的所有属性
                proxy_tool = tool
                proxy_tool.name = prefixed_name  # 修改工具名称

                # 添加到工具映射
                self.tool_map[prefixed_name] = proxy_tool
                all_tools.append(proxy_tool)

        # 更新工具列表
        self.tools = tuple(all_tools)

        logger.info(
            f"Updated tool map with {len(self.tool_map)} tools from {len(self.clients)} clients"
        )

    async def execute_tool(self, name: str, **kwargs) -> Any:
        """执行工具，自动路由到正确的客户端。

        Args:
            name: 工具名称，格式为 "client_name.tool_name" 或 "tool_name"
            **kwargs: 传递给工具的参数

        Returns:
            工具执行的结果

        Raises:
            ValueError: 如果找不到指定的工具
        """
        # 检查是否是带前缀的工具名称
        if "." in name:
            # 格式为 "client_name.tool_name"
            client_name, tool_name = name.split(".", 1)
            if client_name in self.clients:
                # 调用特定客户端的工具
                return await self.clients[client_name].execute(
                    name=tool_name, tool_input=kwargs
                )

        # 如果没有前缀或找不到客户端，尝试在所有客户端中查找工具
        for client in self.clients.values():
            if name in client.tool_map:
                return await client.execute(name=name, tool_input=kwargs)

        # 如果在工具映射中找到，直接执行
        if name in self.tool_map:
            return await super().execute(name=name, tool_input=kwargs)

        # 找不到工具
        return ToolResult(error=f"Tool not found: {name}")

    async def disconnect_all(self) -> None:
        """断开所有客户端连接。"""
        for client_name, client in list(self.clients.items()):
            await client.disconnect()
            logger.info(f"Disconnected from MCP server: {client_name}")

        self.clients = {}
        self.tool_map = {}
        self.tools = tuple()

    async def disconnect_client(self, name: str) -> bool:
        """断开特定客户端的连接。

        Args:
            name: 客户端名称

        Returns:
            是否成功断开连接
        """
        if name in self.clients:
            await self.clients[name].disconnect()
            del self.clients[name]
            await self._update_tool_map()
            logger.info(f"Disconnected from MCP server: {name}")
            return True
        return False

    def get_client(self, name: str) -> Optional[MCPClients]:
        """获取特定客户端实例。

        Args:
            name: 客户端名称

        Returns:
            MCPClients实例，如果不存在则返回None
        """
        return self.clients.get(name)

    def get_client_names(self) -> List[str]:
        """获取所有客户端名称。

        Returns:
            客户端名称列表
        """
        return list(self.clients.keys())

    def get_tools_by_client(self, client_name: str) -> List[str]:
        """获取特定客户端的所有工具名称。

        Args:
            client_name: 客户端名称

        Returns:
            工具名称列表
        """
        return [
            name for name in self.tool_map.keys() if name.startswith(f"{client_name}.")
        ]
