# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from pydantic import BaseModel, Field
from google.adk.agents import LlmAgent
from google.adk.models import Gemini
from google.adk.apps import App
from google.adk.workflow import Workflow, START, node
from google.adk.agents.context import Context
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from google.genai import types


class BillDetails(BaseModel):
    bill_name: str = Field(description="The name of the item/bill, e.g. dinner, electricity, groceries")
    total_amount: float = Field(description="The total amount of the bill")
    friends: list[str] = Field(description="List of friends' names to split the bill with")


# LLM node to parse user input into structured BillDetails
parse_bill = LlmAgent(
    name="parse_bill",
    model=Gemini(
        model="gemini-3.5-flash",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=(
        "Analyze the user's bill splitting request. Parse the name of the bill, "
        "the total amount, and the list of friends' names. Output the structured JSON."
    ),
    output_schema=BillDetails,
)


# Function node to calculate the split share for each person
def calculate_split(node_input: BillDetails) -> dict:
    num_people = len(node_input.friends)
    if num_people == 0:
        share = node_input.total_amount
        summary = f"No friends specified. Total for {node_input.bill_name} is ${node_input.total_amount:.2f}."
    else:
        share = node_input.total_amount / num_people
        friends_list = ", ".join(node_input.friends)
        summary = f"Total for {node_input.bill_name} is ${node_input.total_amount:.2f} split among {num_people} people ({friends_list}). Each person owes ${share:.2f}."
    
    return {
        "summary": summary,
        "bill_name": node_input.bill_name,
        "total_amount": node_input.total_amount,
        "share": share
    }


# Function node with HITL step using RequestInput
@node(rerun_on_resume=True)
async def confirm_split(ctx: Context, node_input: dict):
    if not ctx.resume_inputs or "confirm_split" not in ctx.resume_inputs:
        yield RequestInput(
            interrupt_id="confirm_split",
            message=f"I've calculated the split for '{node_input['bill_name']}':\n{node_input['summary']}\n\nWould you like to finalize this split? (Type 'yes' to confirm or 'no' to cancel)"
        )
        return
    
    user_reply = ctx.resume_inputs["confirm_split"].strip().lower()
    if user_reply in ["yes", "y", "confirm"]:
        yield Event(output=f"Successfully finalized split for {node_input['bill_name']}! {node_input['summary']}", route="approved")
    else:
        yield Event(output="Finalization cancelled. Let me know if you want to split another bill or make changes.", route="cancelled")


from app.workflow import ledger_workflow

root_agent = ledger_workflow

app = App(
    root_agent=root_agent,
    name="app",
)
