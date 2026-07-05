from typing import Any
from google.adk.agents.context import Context
from google.adk.workflow import Workflow, START, node
from google.adk.events.request_input import RequestInput
from google.adk.events.event import Event
from google.genai import types

from app.vision_agent import VisionExtractorAgent
from app.allocation_agent import AllocationAgent


@node(rerun_on_resume=True)
async def collect_input(ctx: Context, node_input: Any):
    """Collects receipt image and instructions from user.

    If not provided initially, interrupts using RequestInput to ask for them.
    Wraps raw strings into a dictionary format compatible with downstream nodes.
    """
    # 1. Check if user resumed with inputs
    if ctx.resume_inputs and "receipt_input" in ctx.resume_inputs:
        user_input = ctx.resume_inputs["receipt_input"]
        if isinstance(user_input, str):
            user_input = {"instructions": user_input, "image": None}
        yield Event(output=user_input)
        return

    instructions = ""
    image_part = None
    has_image = False

    # 2. Check initial input format
    if isinstance(node_input, types.Content):
        for part in node_input.parts:
            if part.inline_data:
                has_image = True
                image_part = part
            elif part.text:
                instructions += part.text
    elif isinstance(node_input, str):
        instructions = node_input
    elif isinstance(node_input, dict):
        yield Event(output=node_input)
        return

    # If we have instructions or an image, proceed.
    if instructions or has_image:
        yield Event(output={"image": image_part, "instructions": instructions})
        return

    # Fallback to prompting user if no instructions or image exists
    yield RequestInput(
        interrupt_id="receipt_input",
        message="Please provide your split instructions, upload a receipt image, or both!"
    )


@node(rerun_on_resume=True)
async def process_split(ctx: Context, node_input: dict):
    """Orchestrates the receipt processing and line item allocation.

    First calls VisionExtractorAgent to parse receipt details (if an image exists),
    then calls AllocationAgent to split items, update the database, and simplify balances.
    """
    instructions = node_input.get("instructions") or ""
    image_part = node_input.get("image")

    if image_part:
        # Run VisionExtractorAgent to parse the receipt image
        vision_input = types.Content(role="user", parts=[image_part])
        vision_result = await ctx.run_node(VisionExtractorAgent, node_input=vision_input)
        
        allocation_prompt = (
            f"Parsed Receipt Details:\n{vision_result}\n\n"
            f"User Split Instructions:\n{instructions}\n\n"
            "Please map the items to people, split shared items, compute tax, "
            "save these records to the database, and show the final simplified balances."
        )
    else:
        # No receipt image was uploaded, perform allocation based solely on instructions
        allocation_prompt = (
            f"User Split Instructions:\n{instructions}\n\n"
            "Please map the items to people, split shared items, compute tax, "
            "save these records to the database, and show the final simplified balances."
        )

    allocation_result = await ctx.run_node(AllocationAgent, node_input=allocation_prompt)
    return allocation_result


ledger_workflow = Workflow(
    name="ledger_workflow",
    description="Orchestrator for receipt parsing, line item allocation, and debt simplification.",
    edges=[
        (START, collect_input),
        (collect_input, process_split),
    ],
)
