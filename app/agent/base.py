from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator

from app.llm import LLM
from app.logger import logger
from app.sandbox.client import SANDBOX_CLIENT
from app.schema import ROLE_TYPE, AgentState, Memory, Message


class BaseAgent(BaseModel, ABC):
    """Abstract base class for managing agent state and execution.

    Provides foundational functionality for state transitions, memory management,
    and a step-based execution loop. Subclasses must implement the `step` method.
    """

    # Core attributes
    name: str = Field(..., description="Unique name of the agent")
    description: Optional[str] = Field(None, description="Optional agent description")

    # Prompts
    system_prompt: Optional[str] = Field(
        None, description="System-level instruction prompt"
    )
    next_step_prompt: Optional[str] = Field(
        None, description="Prompt for determining next action"
    )

    # Dependencies
    llm: LLM = Field(default_factory=LLM, description="Language model instance")
    memory: Memory = Field(default_factory=Memory, description="Agent's memory store")
    state: AgentState = Field(
        default=AgentState.IDLE, description="Current agent state"
    )

    # Execution control
    max_steps: int = Field(default=10, description="Maximum steps before termination")
    current_step: int = Field(default=0, description="Current step in execution")

    # Block state control
    block_reason: Optional[str] = Field(
        None, description="Reason why the agent is blocked"
    )
    user_input_required: bool = Field(
        False, description="Whether user input is required to unblock"
    )

    duplicate_threshold: int = 2

    class Config:
        arbitrary_types_allowed = True
        extra = "allow"  # Allow extra fields for flexibility in subclasses

    @model_validator(mode="after")
    def initialize_agent(self) -> "BaseAgent":
        """Initialize agent with default settings if not provided."""
        if self.llm is None or not isinstance(self.llm, LLM):
            self.llm = LLM(config_name=self.name.lower())
        if not isinstance(self.memory, Memory):
            self.memory = Memory()
        return self

    @asynccontextmanager
    async def state_context(self, new_state: AgentState):
        """Context manager for safe agent state transitions.

        Args:
            new_state: The state to transition to during the context.

        Yields:
            None: Allows execution within the new state.

        Raises:
            ValueError: If the new_state is invalid.
        """
        if not isinstance(new_state, AgentState):
            raise ValueError(f"Invalid state: {new_state}")
        logger.info(f"Transitioning agent state to: {new_state}")
        previous_state = self.state
        self.state = new_state
        try:
            yield
        except Exception as e:
            self.state = AgentState.ERROR  # Transition to ERROR on failure
            raise e
        finally:
            self.state = previous_state  # Revert to previous state

    def update_memory(
        self,
        role: ROLE_TYPE,  # type: ignore
        content: str,
        base64_image: Optional[str] = None,
        **kwargs,
    ) -> None:
        """Add a message to the agent's memory.

        Args:
            role: The role of the message sender (user, system, assistant, tool).
            content: The message content.
            base64_image: Optional base64 encoded image.
            **kwargs: Additional arguments (e.g., tool_call_id for tool messages).

        Raises:
            ValueError: If the role is unsupported.
        """
        message_map = {
            "user": Message.user_message,
            "system": Message.system_message,
            "assistant": Message.assistant_message,
            "tool": lambda content, **kw: Message.tool_message(content, **kw),
        }

        if role not in message_map:
            raise ValueError(f"Unsupported message role: {role}")

        # Create message with appropriate parameters based on role
        kwargs = {"base64_image": base64_image, **(kwargs if role == "tool" else {})}
        self.memory.add_message(message_map[role](content, **kwargs))

    def block(self, reason: str, require_user_input: bool = True) -> None:
        """Block the agent execution and wait for user input or external trigger.

        Args:
            reason: The reason why the agent is blocked
            require_user_input: Whether user input is required to unblock
        """
        self.state = AgentState.BLOCKED
        self.block_reason = reason
        self.user_input_required = require_user_input
        logger.info(f"Agent blocked: {reason}")

    def unblock(self, user_input: Optional[str] = None) -> None:
        """Unblock the agent and continue execution.

        Args:
            user_input: Optional user input to add to memory
        """
        if self.state != AgentState.BLOCKED:
            logger.warning(
                f"Attempted to unblock agent that is not blocked (current state: {self.state})"
            )
            return

        # 如果提供了用户输入，添加到内存中
        if user_input:
            self.update_memory("user", user_input)

        # 恢复到运行状态
        self.state = AgentState.RUNNING
        self.block_reason = None
        self.user_input_required = False
        logger.info("Agent unblocked and continuing execution")

    async def run(self, request: Optional[str] = None) -> str:
        """Execute the agent's main loop asynchronously.

        Args:
            request: Optional initial user request to process.

        Returns:
            A string summarizing the execution results.

        Raises:
            RuntimeError: If the agent is not in IDLE state at start.
        """
        if self.state != AgentState.IDLE and self.state != AgentState.BLOCKED:
            raise RuntimeError(f"Cannot run agent from state: {self.state}")

        # 如果是从IDLE状态开始，处理初始请求
        if self.state == AgentState.IDLE and request:
            self.update_memory("user", request)

        results: List[str] = []

        # 如果是从BLOCKED状态恢复，记录这一点
        if self.state == AgentState.BLOCKED:
            results.append(f"Resuming from blocked state: {self.block_reason}")
            self.state = AgentState.RUNNING  # 手动设置为RUNNING状态

        async with self.state_context(AgentState.RUNNING):
            while (
                self.current_step < self.max_steps
                and self.state != AgentState.FINISHED
                and self.state != AgentState.BLOCKED  # 新增：检查是否进入阻塞状态
            ):
                self.current_step += 1
                logger.info(f"Executing step {self.current_step}/{self.max_steps}")
                step_result = await self.step()

                # 检查是否进入阻塞状态
                if self.state == AgentState.BLOCKED:
                    results.append(f"Step {self.current_step}: {step_result}")
                    results.append(f"Blocked: {self.block_reason}")
                    if self.user_input_required:
                        results.append("Waiting for user input to continue")
                    break  # 跳出循环，暂停执行

                # 检查是否陷入循环
                if self.is_stuck():
                    self.handle_stuck_state()

                results.append(f"Step {self.current_step}: {step_result}")

            # 处理循环结束的原因
            if self.current_step >= self.max_steps and self.state != AgentState.BLOCKED:
                self.current_step = 0
                self.state = AgentState.IDLE
                results.append(f"Terminated: Reached max steps ({self.max_steps})")
            elif self.state == AgentState.BLOCKED:
                # 保持当前步数，以便恢复时继续
                pass

        # 只有在非阻塞状态下才清理资源
        if self.state != AgentState.BLOCKED:
            await SANDBOX_CLIENT.cleanup()

        return "\n".join(results) if results else "No steps executed"

    @abstractmethod
    async def step(self) -> str:
        """Execute a single step in the agent's workflow.

        Must be implemented by subclasses to define specific behavior.
        """

    def handle_stuck_state(self):
        """Handle stuck state by adding a prompt to change strategy"""
        stuck_prompt = "\
        Observed duplicate responses. Consider new strategies and avoid repeating ineffective paths already attempted."
        self.next_step_prompt = f"{stuck_prompt}\n{self.next_step_prompt}"
        logger.warning(f"Agent detected stuck state. Added prompt: {stuck_prompt}")

    def is_stuck(self) -> bool:
        """Check if the agent is stuck in a loop by detecting duplicate content"""
        if len(self.memory.messages) < 2:
            return False

        last_message = self.memory.messages[-1]
        if not last_message.content:
            return False

        # Count identical content occurrences
        duplicate_count = sum(
            1
            for msg in reversed(self.memory.messages[:-1])
            if msg.role == "assistant" and msg.content == last_message.content
        )

        return duplicate_count >= self.duplicate_threshold

    @property
    def messages(self) -> List[Message]:
        """Retrieve a list of messages from the agent's memory."""
        return self.memory.messages

    @messages.setter
    def messages(self, value: List[Message]):
        """Set the list of messages in the agent's memory."""
        self.memory.messages = value
