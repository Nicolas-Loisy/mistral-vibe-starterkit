"""Conversational counterpart to hello.py: pauses to ask for a name in chat."""

import mistralai.workflows as workflows
import mistralai.workflows.plugins.mistralai as workflows_mistralai

from workflows.hello import greet


@workflows.workflow.define(
    name="hello-chat",
    workflow_display_name="Hello Chat",
    workflow_description="Conversational hello-world: asks your name in the chat, then greets you.",
)
class HelloChatWorkflow(workflows.InteractiveWorkflow):
    @workflows.workflow.entrypoint
    async def run(self) -> workflows_mistralai.ChatAssistantWorkflowOutput:
        await workflows_mistralai.send_assistant_message("Hi! What's your name?")

        user_input = await self.wait_for_input(workflows_mistralai.ChatInput())
        name = user_input.message[0].text if user_input.message else "World"

        greeting = await greet(name)

        # The return value is a structured payload for interop, not a chat
        # message: it must be sent explicitly to actually appear in the chat.
        await workflows_mistralai.send_assistant_message(greeting)

        return workflows_mistralai.ChatAssistantWorkflowOutput(
            content=[workflows_mistralai.TextOutput(text=greeting)]
        )
