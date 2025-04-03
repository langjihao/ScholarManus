# interactive_mcp.py - 交互式命令行应用程序
import asyncio
import os
import sys

from app.agent.mcp import MCPAgent
from app.config import config
from app.logger import logger
from app.schema import AgentState


class InteractiveMCPRunner:
    """Interactive runner class for MCP Agent."""

    def __init__(self):
        self.root_path = config.root_path
        self.server_reference = config.mcp_config.server_reference
        self.agent = MCPAgent()

    async def initialize(self) -> None:
        """Initialize the MCP agent with the appropriate connection."""
        logger.info(f"Initializing MCPAgent with connection...")

        try:
            # 使用 SSE 连接到服务
            await self.agent.initialize(
                connection_type="sse",
                server_url="http://localhost:8000/sse",
            )
            logger.info("Connected to FireCrawl MCP service via SSE")
        except Exception as e:
            logger.error(f"Error initializing MCP agent: {str(e)}")
            # 尝试直接使用 stdio 连接
            try:
                await self.agent.initialize(
                    connection_type="stdio",
                    command="npx",
                    args=["-y", "firecrawl-mcp"],
                    env={"FIRECRAWL_API_KEY": "fc-952fa073ed8b421cbc982d896ad51da2"},
                )
                logger.info("Connected to MCP server via stdio")
            except Exception as e2:
                logger.error(f"Failed to connect via stdio as well: {str(e2)}")
                raise

    async def run_interactive(self) -> None:
        """Run the agent in interactive mode."""
        print("\n=== MCP Agent Interactive Mode ===")
        print("Type 'exit', 'quit', or 'q' to exit the program.")
        print("Type 'help' for available commands.")
        print("===================================\n")

        while True:
            try:
                # 使用彩色提示符
                user_input = input("\n\033[1;32m> \033[0m")

                # 检查退出命令
                if user_input.lower() in ["exit", "quit", "q"]:
                    print("Exiting interactive mode...")
                    break

                # 检查帮助命令
                if user_input.lower() == "help":
                    print("\n=== Available Commands ===")
                    print("exit, quit, q - Exit the program")
                    print("help - Show this help message")
                    print("clear - Clear the screen")
                    print("Any other input will be sent to the MCP agent")
                    print("=========================\n")
                    continue

                # 检查清屏命令
                if user_input.lower() == "clear":
                    os.system("cls" if os.name == "nt" else "clear")
                    continue

                # 空输入
                if not user_input.strip():
                    continue

                # 处理用户输入
                print("\n\033[1;34mProcessing your request...\033[0m")
                response = await self.agent.run(user_input)

                # 打印响应
                print(f"\n\033[1;33mAgent Response:\033[0m\n{response}")

                # 检查Agent是否被阻塞
                while self.agent.state == AgentState.BLOCKED:
                    print(
                        f"\n\033[1;35m[Agent需要更多信息]: {self.agent.block_reason}\033[0m"
                    )
                    follow_up_input = input("\n\033[1;32m回复> \033[0m")

                    if follow_up_input.lower() in ["exit", "quit", "q"]:
                        print("Exiting interactive mode...")
                        return

                    # 解除阻塞并继续
                    self.agent.unblock(follow_up_input)
                    print("\n\033[1;34m继续处理...\033[0m")
                    response = await self.agent.run()
                    print(f"\n\033[1;33mAgent Response:\033[0m\n{response}")

            except KeyboardInterrupt:
                print("\nInterrupted by user. Exiting...")
                break
            except Exception as e:
                print(f"\n\033[1;31mError: {str(e)}\033[0m")

    async def cleanup(self) -> None:
        """Clean up agent resources."""
        try:
            if hasattr(self, "agent") and self.agent:
                await self.agent.cleanup()
                logger.info("Agent resources cleaned up")
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")


async def main():
    """Main function to run the interactive MCP agent."""
    runner = InteractiveMCPRunner()

    try:
        # 初始化MCP代理
        await runner.initialize()

        # 运行交互模式
        await runner.run_interactive()
    except Exception as e:
        logger.error(f"Error running interactive mode: {str(e)}")
        print(f"\n\033[1;31mFatal error: {str(e)}\033[0m")
        return 1
    finally:
        # 清理资源
        await runner.cleanup()

    return 0


if __name__ == "__main__":
    # 运行主函数
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
