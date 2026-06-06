from anthropic import Anthropic
from config import MODEL, SYSTEM_PROMPT
from tools import TOOL_DEFINITIONS, execute_tool

_MAX_HISTORY = 40  # keep last ~10 real exchanges (tool calls add extra messages)


class JarvisAI:
    def __init__(self):
        self.client = Anthropic()
        self.history: list = []
        self._memory_context: str = ""

    def set_memory_context(self, context: str) -> None:
        self._memory_context = context

    def process(self, user_message: str, on_text=None, on_tool=None) -> str:
        self.history.append({"role": "user", "content": user_message})
        self._trim_history()

        system = SYSTEM_PROMPT
        if self._memory_context:
            system = f"{SYSTEM_PROMPT}\n\n{self._memory_context}"

        while True:
            with self.client.messages.stream(
                model=MODEL,
                max_tokens=1024,
                system=system,
                messages=self.history,
                tools=TOOL_DEFINITIONS,
            ) as stream:
                for event in stream:
                    if (
                        on_text
                        and hasattr(event, "type")
                        and event.type == "content_block_delta"
                        and hasattr(event, "delta")
                        and hasattr(event.delta, "text")
                    ):
                        on_text(event.delta.text)

                response = stream.get_final_message()

            self.history.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn":
                return "".join(
                    b.text for b in response.content if hasattr(b, "text")
                )

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        if on_tool:
                            on_tool(block.name, block.input)
                        result = execute_tool(block.name, block.input)
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": result,
                            }
                        )
                self.history.append({"role": "user", "content": tool_results})

    def clear_history(self):
        self.history = []

    def _trim_history(self):
        if len(self.history) <= _MAX_HISTORY:
            return
        self.history = self.history[-_MAX_HISTORY:]
        # After slicing, drop any leading messages until we reach a real user
        # turn (string content). A slice boundary may land inside a tool-use
        # exchange, leaving a stale tool_result as the first message — the API
        # rejects that as an invalid history.
        while self.history:
            msg = self.history[0]
            if msg.get("role") == "user" and isinstance(msg.get("content"), str):
                break
            self.history.pop(0)
