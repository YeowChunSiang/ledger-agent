from google.adk.agents import LlmAgent
from google.adk.models import Gemini
from google.genai import types

# Import tools
from app.debt_simplification import simplify_debts_tool
from mcp_server import (
    create_user,
    get_users,
    create_group,
    get_groups,
    add_group_member,
    create_receipt,
    add_line_item,
    add_line_item_split,
    get_group_balances,
)

AllocationAgent = LlmAgent(
    name="AllocationAgent",
    model=Gemini(
        model="gemini-3.5-flash",
        retry_options=types.HttpRetryOptions(attempts=10),
    ),
    instruction=(
        "You are an AI receipt item allocator. You receive a natural language prompt "
        "detailing who bought what, and optionally a JSON array of receipt items. "
        "Your job is to:\n"
        "1. Map each item to the correct person.\n"
        "2. If no parsed receipt JSON is provided, extract the items, quantities, and pricing details "
        "directly from the user's natural language instructions. Do NOT ask the user for a JSON array if they "
        "have already described the items and costs in the text prompt.\n"
        "3. Split shared items evenly among the users sharing them.\n"
        "4. Distribute the tax proportionally based on each person's share of the subtotal.\n"
        "5. **CRITICAL (Trip Continuation)**: Before creating a new group, ALWAYS check existing groups with `get_groups`. "
        "If a group exists (e.g. for the trip/event), reuse its ID instead of calling `create_group`. "
        "Similarly, check existing users with `get_users` and reuse their IDs instead of calling `create_user` again.\n"
        "6. Use the provided database tools to persist users, groups, receipts, line items, and splits.\n"
        "7. Use simplify_debts_tool to calculate and show the minimum necessary transfers to settle all balances.\n"
        "8. At the end of your response, always generate a beautiful Mermaid pie chart showing the expense distribution (either by member share or by items). Format it inside a markdown code block tagged with 'mermaid'. E.g. 'pie title Expense Distribution\\n  \"Alice\" : 20.00\\n  \"Bob\" : 30.00'"
    ),
    tools=[
        simplify_debts_tool,
        create_user,
        get_users,
        create_group,
        get_groups,
        add_group_member,
        create_receipt,
        add_line_item,
        add_line_item_split,
        get_group_balances,
    ],
)
