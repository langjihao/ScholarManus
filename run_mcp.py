#!/usr/bin/env python
import argparse
import asyncio
import sys

from app.agent.mcp import MCPAgent
from app.config import config
from app.logger import logger
from app.schema import AgentState


class MCPRunner:
    """Runner class for MCP Agent with proper path handling and configuration."""

    def __init__(self):
        self.root_path = config.root_path
        self.server_reference = config.mcp_config.server_reference
        self.agent = MCPAgent()

    async def initialize(
        self,
        connection_type: str,
        server_url: str | None = None,
    ) -> None:
        """Initialize the MCP agent with the appropriate connection."""
        logger.info(f"Initializing MCPAgent with {connection_type} connection...")

        await self.agent.initialize(
            connection_type="sse",
            server_url="http://localhost:8000/sse",
        )

        logger.info(f"Connected to MCP server via {connection_type}")

    async def run_interactive(self) -> None:
        """Run the agent in interactive mode."""
        print("\nMCP Agent Interactive Mode (type 'exit' to quit)\n")

        # 初始提示
        user_input = input("\nEnter your request: ")
        if user_input.lower() in ["exit", "quit", "q"]:
            return

        while True:
            # 运行Agent
            response = await self.agent.run(user_input)
            print(f"\nAgent: {response}")

            # 检查Agent是否被阻塞
            if self.agent.state == AgentState.BLOCKED:
                print(f"\n[Agent需要更多信息]: {self.agent.block_reason}")
                user_input = input("\n您的回复: ")

                if user_input.lower() in ["exit", "quit", "q"]:
                    break

                # 解除阻塞并继续
                self.agent.unblock(user_input)
            else:
                # 正常情况下获取下一个输入
                user_input = input("\nEnter your request: ")
                if user_input.lower() in ["exit", "quit", "q"]:
                    break

    async def run_single_prompt(self, prompt: str) -> None:
        """Run the agent with a single prompt."""
        response = await self.agent.run(prompt)
        print(f"\nAgent: {response}")

        # 处理可能的阻塞状态
        while self.agent.state == AgentState.BLOCKED:
            print(f"\n[Agent需要更多信息]: {self.agent.block_reason}")
            user_input = input("\n您的回复: ")

            if user_input.lower() in ["exit", "quit", "q"]:
                break

            self.agent.unblock(user_input)
            response = await self.agent.run()
            print(f"\nAgent: {response}")

    async def run_default(self) -> None:
        """Run the agent in default mode."""
        prompt = input("Enter your prompt: ")
        if not prompt.strip():
            logger.warning("Empty prompt provided.")
            return

        logger.warning("Processing your request...")
        response = await self.agent.run(prompt)
        print(f"\nAgent: {response}")

        # 处理可能的阻塞状态
        while self.agent.state == AgentState.BLOCKED:
            print(f"\n[Agent需要更多信息]: {self.agent.block_reason}")
            user_input = input("\n您的回复: ")

            if user_input.lower() in ["exit", "quit", "q"]:
                break

            self.agent.unblock(user_input)
            response = await self.agent.run()
            print(f"\nAgent: {response}")

        logger.info("Request processing completed.")

    async def cleanup(self) -> None:
        """Clean up agent resources."""
        await self.agent.cleanup()
        logger.info("Session ended")


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Run the MCP Agent")
    parser.add_argument(
        "--connection",
        "-c",
        choices=["stdio", "sse"],
        default="stdio",
        help="Connection type: stdio or sse",
    )
    parser.add_argument(
        "--server-url",
        default="http://127.0.0.1:8000/sse",
        help="URL for SSE connection",
    )
    parser.add_argument(
        "--interactive", "-i", action="store_true", help="Run in interactive mode"
    )
    parser.add_argument("--prompt", "-p", help="Single prompt to execute and exit")
    return parser.parse_args()


async def run_mcp() -> None:
    """Main entry point for the MCP runner."""
    # 打印ScholarManus字符画
    print(
        r"""
   _____      __          __           __  ___
  / ___/_____/ /_  ____  / /___ ______/  |/  /___ _____  __  _______
  \__ \/ ___/ __ \/ __ \/ / __ `/ ___/ /|_/ / __ `/ __ \/ / / / ___/
 ___/ / /__/ / / / /_/ / / /_/ / /  / /  / / /_/ / / / / /_/ (__  )
/____/\___/_/ /_/\____/_/\__,_/_/  /_/  /_/\__,_/_/ /_/\__,_/____/

    """
    )

    args = parse_args()
    runner = MCPRunner()

    try:
        await runner.initialize(args.connection, args.server_url)

        if args.prompt:
            await runner.run_single_prompt(args.prompt)
        elif args.interactive:
            await runner.run_interactive()
        else:
            await runner.run_default()

    except KeyboardInterrupt:
        logger.info("Program interrupted by user")
    except Exception as e:
        logger.error(f"Error running MCPAgent: {str(e)}", exc_info=True)
        sys.exit(1)
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(run_mcp())
