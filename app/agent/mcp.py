from typing import Any, Dict, List, Optional, Tuple

from pydantic import Field

from app.agent.toolcall import ToolCallAgent
from app.logger import logger
from app.prompt.professor_mcp import (
    MULTIMEDIA_RESPONSE_PROMPT,
    NEXT_STEP_PROMPT,
    SYSTEM_PROMPT,
)
from app.schema import AgentState, Message
from app.tool.base import ToolResult
from app.tool.mcp import MCPClients


class MCPAgent(ToolCallAgent):
    """Agent for interacting with MCP (Model Context Protocol) servers.

    This agent connects to an MCP server using either SSE or stdio transport
    and makes the server's tools available through the agent's tool interface.
    """

    name: str = "ScholarManus"
    description: str = "An agent that connects to an MCP server and uses its tools."

    system_prompt: str = SYSTEM_PROMPT
    next_step_prompt: str = NEXT_STEP_PROMPT

    # Initialize MCP tool collection
    mcp_clients: MCPClients = Field(default_factory=MCPClients)
    available_tools: MCPClients = None  # Will be set in initialize()

    max_steps: int = 20
    connection_type: str = "stdio"  # "stdio" or "sse"

    # Track tool schemas to detect changes
    tool_schemas: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    _refresh_tools_interval: int = 5  # Refresh tools every N steps

    # Special tool names that should trigger termination
    special_tool_names: List[str] = Field(default_factory=lambda: ["terminate"])

    async def initialize(
        self,
        connection_type: Optional[str] = None,
        server_url: Optional[str] = None,
        command: Optional[str] = None,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> None:
        """Initialize the MCP connection.

        Args:
            connection_type: Type of connection to use ("stdio" or "sse")
            server_url: URL of the MCP server (for SSE connection)
            command: Command to run (for stdio connection)
            args: Arguments for the command (for stdio connection)
        """
        if connection_type:
            self.connection_type = connection_type

        # Connect to the MCP server based on connection type
        if self.connection_type == "sse":
            if not server_url:
                raise ValueError("Server URL is required for SSE connection")
            await self.mcp_clients.connect_sse(server_url=server_url)
        elif self.connection_type == "stdio":
            if not command:
                raise ValueError("Command is required for stdio connection")
            await self.mcp_clients.connect_stdio(
                command=command, args=args or [], env=env
            )
        else:
            raise ValueError(f"Unsupported connection type: {self.connection_type}")

        # Set available_tools to our MCP instance
        self.available_tools = self.mcp_clients

        # Store initial tool schemas
        await self._refresh_tools()

        # Add system message about available tools
        tool_names = list(self.mcp_clients.tool_map.keys())
        tools_info = ", ".join(tool_names)

        # Add system prompt and available tools information
        self.memory.add_message(
            Message.system_message(
                f"{self.system_prompt}\n\nAvailable MCP tools: {tools_info}"
            )
        )

    async def _refresh_tools(self) -> Tuple[List[str], List[str]]:
        """Refresh the list of available tools from the MCP server.

        Returns:
            A tuple of (added_tools, removed_tools)
        """
        if not self.mcp_clients.session:
            return [], []

        # Get current tool schemas directly from the server
        response = await self.mcp_clients.session.list_tools()
        current_tools = {tool.name: tool.inputSchema for tool in response.tools}

        # Determine added, removed, and changed tools
        current_names = set(current_tools.keys())
        previous_names = set(self.tool_schemas.keys())

        added_tools = list(current_names - previous_names)
        removed_tools = list(previous_names - current_names)

        # Check for schema changes in existing tools
        changed_tools = []
        for name in current_names.intersection(previous_names):
            if current_tools[name] != self.tool_schemas.get(name):
                changed_tools.append(name)

        # Update stored schemas
        self.tool_schemas = current_tools

        # Log and notify about changes
        if added_tools:
            logger.info(f"Added MCP tools: {added_tools}")
            self.memory.add_message(
                Message.system_message(f"New tools available: {', '.join(added_tools)}")
            )
        if removed_tools:
            logger.info(f"Removed MCP tools: {removed_tools}")
            self.memory.add_message(
                Message.system_message(
                    f"Tools no longer available: {', '.join(removed_tools)}"
                )
            )
        if changed_tools:
            logger.info(f"Changed MCP tools: {changed_tools}")

        return added_tools, removed_tools

    def _needs_user_input(self, message: str) -> Tuple[bool, str]:
        """检测消息是否需要用户输入，增强版

        使用多种方法判断消息是否需要用户输入，包括：
        1. 问句检测（问号、疑问词）
        2. 指令性语句检测（请提供、请告诉我等）
        3. 上下文分析（排除修辞性问句）

        Args:
            message: 需要检测的消息内容

        Returns:
            Tuple[bool, str]: (是否需要输入, 阻塞原因)
        """
        import re

        # 如果消息为空，不需要用户输入
        if not message or not message.strip():
            return False, ""

        # 直接检查是否包含问号（包括中英文问号）
        has_question_mark = "?" in message or "？" in message

        # 预处理：分割成句子进行分析
        # 使用更复杂的正则表达式来正确分割句子，同时处理中英文标点
        sentences = re.split(r"(?<=[.!?。！？])\s*", message.strip())
        sentences = [s.strip() for s in sentences if s.strip()]

        if not sentences:
            return False, ""

        # 定义各类判断标准

        # 1. 明确的指令性语句，直接要求用户提供信息
        instruction_patterns = [
            r"请(?:问|提供|输入|告诉|说明|描述|指定|选择|确认|回答|解释|分享|上传)",
            r"(?:提供|输入|告诉|说明|描述|指定|选择|确认)(?:一下|下)",
            r"(?:能|可以|可否|请)(?:告诉|提供|说明|描述|解释)",
            r"有(?:什么|何|哪些)(?:.{0,10})?(?:问题|疑问|不明白的)",
            r"(?:please|kindly|could you|can you|would you)(?:\s+\w+)?\s+(?:provide|tell|share|explain|describe|confirm|specify|select|input)",
            r"(?:need|require|want)(?:\s+\w+)?\s+(?:your|the|some|more)(?:\s+\w+)?\s+(?:input|information|details|clarification|confirmation)",
            r"how can I help",
        ]

        # 2. 常见疑问词和疑问句模式（不仅仅是开头）
        question_patterns = [
            # 中文疑问词
            r"(?:什么|如何|怎么|怎样|为什么|为何|哪些|哪个|哪里|何时|何地|谁|是否)",
            r"(?:能否|可否|是否)(?:\s+\w+)?",
            r"有(?:什么|哪些)(?:.{0,15})?(?:可以|能够|需要)",
            r"请问",  # 添加"请问"作为明确的问句标识
            # 英文疑问词
            r"(?:what|how|why|when|where|which|who|whom|whose)",
            r"(?:do|does|did|is|are|was|were|have|has|had|can|could|will|would|should|shall|may|might)\s+(?:you|i|we|they|he|she|it)",
        ]

        # 3. 明确的修辞性问句，不需要用户回答
        rhetorical_patterns = [
            r"(?:不是吗|对吧|对不对|是不是|是吧|不是吗|难道不|难道|不是么)",
            r"(?:wouldn\'t you agree|isn\'t it|doesn\'t it|don\'t you think|right\?)",
            r"(?:想象一下|假设|假如|如果).*[?？]",
            r"(?:imagine|suppose|what if|assuming).*[?？]",
        ]

        # 存储需要用户输入的句子
        user_input_sentences = []

        # 分析每个句子
        for sentence in sentences:
            # 跳过太短的句子（可能是噪音）
            if len(sentence) < 3:
                continue

            # 检查是否是问句（包含问号，包括中英文问号）
            is_question = "?" in sentence or "？" in sentence

            # 检查是否包含指令性语句
            has_instruction = any(
                re.search(pattern, sentence, re.IGNORECASE)
                for pattern in instruction_patterns
            )

            # 检查是否包含疑问词或疑问句模式（不仅仅检查开头）
            has_question_pattern = any(
                re.search(pattern, sentence, re.IGNORECASE)
                for pattern in question_patterns
            )

            # 检查是否是修辞性问句
            is_rhetorical = any(
                re.search(pattern, sentence, re.IGNORECASE)
                for pattern in rhetorical_patterns
            )

            # 判断逻辑：
            # 1. 如果是明确的指令性语句，需要用户输入
            # 2. 如果是问句且不是修辞性问句，需要用户输入
            # 3. 如果包含疑问词或疑问句模式且不是修辞性问句，需要用户输入
            if (
                has_instruction
                or (is_question and not is_rhetorical)
                or (has_question_pattern and not is_rhetorical)
            ):
                user_input_sentences.append(sentence)

        # 特殊情况：如果整个消息包含问号但没有找到需要用户输入的句子
        # 这可能是因为句子分割不正确或者其他原因
        if has_question_mark and not user_input_sentences:
            # 尝试找出包含问号的部分作为需要用户输入的句子
            question_parts = re.findall(r"[^.!?。！？]*[?？][^.!?。！？]*", message)
            for part in question_parts:
                if len(part.strip()) > 3 and not any(
                    re.search(pattern, part, re.IGNORECASE)
                    for pattern in rhetorical_patterns
                ):
                    user_input_sentences.append(part.strip())

        # 如果没有找到需要用户输入的句子
        if not user_input_sentences:
            return False, ""

        # 组合所有需要用户输入的句子作为阻塞原因
        block_reason = " ".join(user_input_sentences)
        return False, block_reason

    async def think(self) -> bool:
        """Process current state and decide next action."""
        # Check MCP session and tools availability
        if not self.mcp_clients.session or not self.mcp_clients.tool_map:
            logger.info("MCP service is no longer available, ending interaction")
            self.state = AgentState.FINISHED
            return False

        # Refresh tools periodically
        if self.current_step % self._refresh_tools_interval == 0:
            await self._refresh_tools()
            # All tools removed indicates shutdown
            if not self.mcp_clients.tool_map:
                logger.info("MCP service has shut down, ending interaction")
                self.state = AgentState.FINISHED
                return False

        # Use the parent class's think method
        result = await super().think()

        # 检查最后一条消息是否需要用户输入
        if result and len(self.memory.messages) > 0:
            last_message = self.memory.messages[-1]
            if last_message.role == "assistant" and last_message.content:
                needs_input, block_reason = self._needs_user_input(last_message.content)
                if needs_input:
                    # 进入阻塞状态
                    self.block(reason=block_reason, require_user_input=True)
                    logger.info(f"Agent自动进入阻塞状态: {block_reason}")
            else:
                logger.debug(
                    f"最后一条消息不是assistant或没有内容: {last_message.role}"
                )
        else:
            logger.debug(
                f"没有结果或没有消息: result={result}, messages={len(self.memory.messages)}"
            )

        return result

    async def _handle_special_tool(self, name: str, result: Any, **kwargs) -> None:
        """Handle special tool execution and state changes"""
        # First process with parent handler
        await super()._handle_special_tool(name, result, **kwargs)

        # Handle multimedia responses
        if isinstance(result, ToolResult) and result.base64_image:
            self.memory.add_message(
                Message.system_message(
                    MULTIMEDIA_RESPONSE_PROMPT.format(tool_name=name)
                )
            )

    def _should_finish_execution(self, name: str, **kwargs) -> bool:
        """Determine if tool execution should finish the agent"""
        # Terminate if the tool name is 'terminate'
        return name.lower() == "terminate"

    async def cleanup(self) -> None:
        """Clean up MCP connection when done."""
        if self.mcp_clients.session:
            await self.mcp_clients.disconnect()
            logger.info("MCP connection closed")

    async def run(self, request: Optional[str] = None) -> str:
        """Run the agent with cleanup when done."""
        try:
            result = await super().run(request)
            return result
        finally:
            # Ensure cleanup happens even if there's an error
            await self.cleanup()
