# app_gradio_simple.py - 简化版，适合单用户使用
import asyncio
import mimetypes
import os
from pathlib import Path

import gradio as gr

from app.agent.mcp import MCPAgent
from app.config import config
from app.logger import logger

# 初始化工作目录
WORKSPACE = "workspace"
os.makedirs(WORKSPACE, exist_ok=True)


class MCPRunner:
    """Runner class for MCP Agent with proper path handling and configuration."""

    def __init__(self):
        self.root_path = config.root_path
        self.server_reference = config.mcp_config.server_reference
        self.agent = MCPAgent()
        self.initialized = False

    async def initialize(self) -> None:
        """Initialize the MCP agent with the appropriate connection."""
        if self.initialized:
            return

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

        self.initialized = True

    async def run_prompt(self, prompt: str) -> str:
        """Run the agent with a prompt and return the result."""
        if not self.initialized:
            await self.initialize()

        result = await self.agent.run(prompt)
        return result

    async def cleanup(self) -> None:
        """Clean up agent resources."""
        if hasattr(self, "agent") and self.agent:
            await self.agent.cleanup()
            logger.info("Agent resources cleaned up")
            self.initialized = False


def get_files_pathlib(root_dir):
    """使用pathlib递归获取文件路径"""
    root = Path(root_dir)
    return [str(path) for path in root.glob("**/*") if path.is_file()]


# 创建全局MCPRunner实例
mcp_runner = MCPRunner()


# Gradio 界面实现
def list_files():
    """列出工作空间中的文件"""
    return os.listdir(WORKSPACE)


def view_file(filename):
    """查看文件内容"""
    if not filename:
        return "请选择文件"

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
    """处理用户消息并返回响应"""
    # 使用asyncio运行异步任务
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # 创建初始消息
    history = history + [{"role": "user", "content": message}]

    # 添加一个加载状态提示
    loading_message = "正在思考中，请稍候..."
    history = history + [{"role": "assistant", "content": loading_message}]

    try:
        # 初始化并运行MCP代理
        result = loop.run_until_complete(mcp_runner.run_prompt(message))

        # 格式化响应内容
        formatted_result = result

        # 如果响应为空，提供友好提示
        if not formatted_result or formatted_result.strip() == "":
            formatted_result = "抱歉，我无法生成有效的回答。请尝试重新表述您的问题。"

        # 更新历史记录
        history[-1]["content"] = formatted_result
        return history
    except Exception as e:
        # 提供更友好的错误信息
        error_type = type(e).__name__
        error_message = str(e)

        user_friendly_message = "处理您的请求时遇到了问题。"

        # 根据错误类型提供更具体的信息
        if "ConnectionError" in error_type or "Timeout" in error_type:
            user_friendly_message += (
                "可能是网络连接问题，请检查您的网络连接并稍后再试。"
            )
        elif "ValueError" in error_type:
            user_friendly_message += "您的输入可能有误，请尝试重新表述您的问题。"
        else:
            user_friendly_message += f"错误详情: {error_message}"

        logger.error(f"处理消息时出错: {error_type} - {error_message}")
        history[-1]["content"] = user_friendly_message
        return history
    finally:
        loop.close()


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


# 应用程序关闭时清理资源
def cleanup_resources():
    """清理应用程序资源"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(mcp_runner.cleanup())
    finally:
        loop.close()


# 创建并启动Gradio应用
if __name__ == "__main__":
    # 确保工作目录存在
    os.makedirs(WORKSPACE, exist_ok=True)

    # 构建Gradio界面
    demo = build_gradio_interface()

    try:
        # 启动Gradio服务器
        demo.launch(server_name="0.0.0.0", server_port=7860)
    finally:
        # 应用程序关闭时清理资源
        cleanup_resources()
