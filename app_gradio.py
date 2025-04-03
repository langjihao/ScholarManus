# app_gradio.py
import asyncio
import mimetypes
import os
import queue
import sys
import threading
import time
from pathlib import Path

import gradio as gr

from app.agent.mcp import MCPAgent
from app.config import config
from app.logger import log_queue, logger

# 初始化工作目录
WORKSPACE = "workspace"
os.makedirs(WORKSPACE, exist_ok=True)
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


# 线程包装器
def run_async_task(message):
    """在新线程中运行异步任务"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main(message))
    loop.close()


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


# Gradio 界面实现
def list_files():
    """列出工作空间中的文件"""
    return os.listdir(WORKSPACE)


def view_file(filename):
    """查看文件内容"""
    file_path = os.path.join(WORKSPACE, filename)
    if os.path.isfile(file_path):
        mime_type, _ = mimetypes.guess_type(filename)
        if mime_type and mime_type.startswith("text/"):
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            return content
        elif mime_type == "application/pdf":
            return file_path  # 返回文件路径，让Gradio处理PDF显示
        else:
            return file_path  # 返回文件路径，让Gradio处理其他类型文件
    else:
        return "文件不存在"


def process_message(message, history):
    """处理用户消息并返回流式响应"""
    # 清空日志文件
    if os.path.exists(LOG_FILE):
        os.remove(LOG_FILE)

    # 启动异步任务线程
    task_thread = threading.Thread(target=run_async_task, args=(message,))
    task_thread.start()

    start_time = time.time()
    full_response = ""

    # 创建初始消息
    history = history + [{"role": "user", "content": message}]
    history = history + [{"role": "assistant", "content": ""}]
    yield history

    # 用于跟踪是否已经开始接收实际响应
    response_started = False

    while task_thread.is_alive() or not log_queue.empty():
        # 超时检查
        if time.time() - start_time > PROCESS_TIMEOUT:
            if not response_started:
                full_response = "处理请求超时，请稍后再试或尝试简化您的问题。"
            else:
                full_response += "\n\n(处理超时，响应可能不完整)"
            history[-1]["content"] = full_response
            yield history
            break

        try:
            new_content = log_queue.get(timeout=0.1)
            if new_content:
                # 过滤掉不必要的系统日志信息
                if "INFO" in new_content and (
                    "Token usage" in new_content or "Executing step" in new_content
                ):
                    continue

                # 检测是否包含思考内容
                if "✨ mcp_agent's thoughts:" in new_content:
                    # 提取思考内容并格式化
                    thought = new_content.split("✨ mcp_agent's thoughts:")[1].strip()
                    if not response_started:
                        full_response = thought
                        response_started = True
                    else:
                        full_response += "\n\n" + thought
                else:
                    # 普通内容
                    if not response_started and new_content.strip():
                        response_started = True

                    if response_started:
                        full_response += new_content

                # 更新历史记录
                history[-1]["content"] = full_response
                yield history
        except queue.Empty:
            pass

        # 无新内容时暂停
        time.sleep(0.1)

    # 如果没有实际响应，添加一个友好的提示
    if not response_started:
        full_response = "我正在处理您的请求，但目前没有生成有效的响应。请尝试重新提问或换一种表述方式。"
        history[-1]["content"] = full_response
        yield history


def create_file_viewer():
    """创建文件查看器组件"""
    with gr.Column():
        files = gr.Dropdown(label="选择文件", choices=list_files(), interactive=True)

        # 刷新文件列表按钮
        refresh_btn = gr.Button("刷新文件列表")

        # 文件内容显示
        file_content = gr.Textbox(
            label="文件内容", lines=20, max_lines=50, interactive=False
        )

        # 刷新按钮点击事件
        refresh_btn.click(fn=list_files, outputs=files)

        # 文件选择事件
        files.change(fn=view_file, inputs=files, outputs=file_content)

    return files, file_content


def build_gradio_interface():
    """构建Gradio界面"""
    with gr.Blocks(title="智能助手") as demo:
        gr.Markdown("# 智能助手")

        with gr.Tabs():
            # 聊天选项卡
            with gr.TabItem("聊天"):
                chatbot = gr.Chatbot(height=500, type="messages")
                msg = gr.Textbox(placeholder="输入您的问题...", show_label=False)

                msg.submit(
                    fn=process_message,
                    inputs=[msg, chatbot],
                    outputs=chatbot,
                    queue=True,
                ).then(lambda: "", None, msg, queue=False)

            # 文件浏览选项卡
            with gr.TabItem("文件浏览"):
                files, file_content = create_file_viewer()

    return demo


# 创建并启动Gradio应用
if __name__ == "__main__":
    # 确保工作目录存在
    os.makedirs(WORKSPACE, exist_ok=True)

    # 构建Gradio界面
    demo = build_gradio_interface()

    # 启动Gradio服务器
    demo.launch(server_name="0.0.0.0", server_port=7860)
