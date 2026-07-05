from pydantic import BaseModel, Field
from google.adk.agents import LlmAgent
from google.adk.models import Gemini
from google.genai import types


class ReceiptItem(BaseModel):
    item_name: str = Field(description="Name of the parsed item on the receipt")
    quantity: int = Field(description="Quantity of the item purchased")
    price: float = Field(description="Unit price of the item")
    subtotal: float = Field(description="Subtotal for this item (quantity * price)")
    tax: float = Field(description="Estimated or indicated tax for this item")
    total: float = Field(description="Total cost for this item (subtotal + tax)")


class ReceiptData(BaseModel):
    items: list[ReceiptItem] = Field(description="A structured JSON array of all parsed items on the receipt")


VisionExtractorAgent = LlmAgent(
    name="VisionExtractorAgent",
    model=Gemini(
        model="gemini-3.5-flash",
        retry_options=types.HttpRetryOptions(attempts=10),
    ),
    instruction=(
        "You are an expert receipt parser. Analyze the provided receipt image and extract "
        "all line items. For each item, populate its name, quantity, unit price, "
        "subtotal, tax, and total. You must strictly output the structured data matching the schema."
    ),
    output_schema=ReceiptData,
)
