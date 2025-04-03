# app.py
import asyncio
import mimetypes
import os
import queue
import sys
import threading
import time
from pathlib import Path

from flask import (
    Flask,
    Response,
    jsonify,
    render_template,
    request,
    send_from_directory,
)

from app.agent.mcp import MCPAgent
from app.config import config
from app.logger import log_queue, logger

app = Flask(__name__)
app.config["WORKSPACE"] = "workspace"

# 初始化工作目录
os.makedirs(app.config["WORKSPACE"], exist_ok=True)
LOG_FILE = "logs/root_stream.log"
FILE_CHECK_INTERVAL = 2  # 文件检查间隔（秒）
PROCESS_TIMEOUT = 600  # 最长处理时间（秒）


class MCPRunner:
    """Runner class for MCP Agent with proper path handling and configuration."""

    def __init__(self):
        self.root_path = config.root_path
        self.server_reference = config.mcp_config.server_reference
        self.agent = MCPAgent()

    async def initialize(
        self,
    ) -> None:
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

    async def run_interactive(self) -> None:
        """Run the agent in interactive mode."""
        print("\nMCP Agent Interactive Mode (type 'exit' to quit)\n")
        while True:
            user_input = input("\nEnter your request: ")
            if user_input.lower() in ["exit", "quit", "q"]:
                break
            response = await self.agent.run(user_input)
            print(f"\nAgent: {response}")

    async def run_single_prompt(self, prompt: str) -> None:
        """Run the agent with a single prompt."""
        await self.agent.run(prompt)

    async def run_default(self) -> None:
        """Run the agent in default mode."""
        prompt = input("Enter your prompt: ")
        if not prompt.strip():
            logger.warning("Empty prompt provided.")
            return

        logger.warning("Processing your request...")
        await self.agent.run(prompt)
        logger.info("Request processing completed.")

    async def cleanup(self) -> None:
        """Clean up agent resources."""
        try:
            # 清理代理资源
            if hasattr(self, "agent") and self.agent:
                await self.agent.cleanup()
                logger.info("Agent resources cleaned up")

            # 如果有服务器进程，终止它
            if hasattr(self, "server_process") and self.server_process:
                try:
                    self.server_process.terminate()
                    # 等待进程结束
                    self.server_process.wait(timeout=5)
                    logger.info("Server process terminated")
                except Exception as e:
                    logger.error(f"Error terminating server process: {str(e)}")
                    # 强制终止
                    try:
                        self.server_process.kill()
                        logger.info("Server process killed")
                    except:
                        pass
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")
        finally:
            logger.info("Session ended")


def get_files_pathlib(root_dir):
    """使用pathlib递归获取文件路径"""
    root = Path(root_dir)
    return [str(path) for path in root.glob("**/*") if path.is_file()]


@app.route("/")
def index():
    files = os.listdir(app.config["WORKSPACE"])
    return render_template("index.html", files=files)


@app.route("/file/<filename>")
def file(filename):
    file_path = os.path.join(app.config["WORKSPACE"], filename)
    if os.path.isfile(file_path):
        mime_type, _ = mimetypes.guess_type(filename)
        if mime_type and mime_type.startswith("text/"):
            if mime_type == "text/html":
                return send_from_directory(app.config["WORKSPACE"], filename)
            else:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                return render_template("code.html", filename=filename, content=content)
        elif mime_type == "application/pdf":
            return send_from_directory(app.config["WORKSPACE"], filename)

        else:
            return send_from_directory(app.config["WORKSPACE"], filename)
    else:
        return "File not found", 404


async def main(prompt=None):
    """主异步函数，初始化并运行代理。"""
    try:
        agent = MCPRunner()
        await agent.initialize()

        if prompt:
            # 如果提供了提示，则运行单个提示
            await agent.run_single_prompt(prompt)
        else:
            # 否则运行交互模式
            logger.info("启动交互模式")
            await agent.run_interactive()
    except Exception as e:
        logger.error(f"运行代理时出错: {str(e)}")
        raise


# 线程包装器
def run_async_task(message):
    """在新线程中运行异步任务"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main(message))
    loop.close()


@app.route("/api/chat-stream", methods=["POST"])
def chat_stream():
    """流式日志接口"""
    # 清空日志文件
    if os.path.exists(LOG_FILE):
        os.remove(LOG_FILE)

    # 获取请求数据
    prompt = request.get_json()
    print("收到请求:", prompt)

    # 启动异步任务线程
    task_thread = threading.Thread(target=run_async_task, args=(prompt["message"],))
    task_thread.start()

    # 流式生成器
    def generate():
        start_time = time.time()

        while task_thread.is_alive() or not log_queue.empty():
            # 超时检查
            if time.time() - start_time > PROCESS_TIMEOUT:
                yield "\n[错误] 处理超时\n"
                break
            new_content = ""
            try:
                new_content = log_queue.get(timeout=0.1)
            except queue.Empty:
                pass

            if new_content:
                yield new_content

            # 无新内容时暂停
            if not new_content:
                time.sleep(FILE_CHECK_INTERVAL)

        # 最终确认
        yield "\n[完成] 处理结束\n"

    return Response(generate(), mimetype="text/plain")


if __name__ == "__main__":
    # 正确运行异步函数
    app.run(debug=True)
