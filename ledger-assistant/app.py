import streamlit as st
import pandas as pd
import plotly.express as px
import sqlite3
import os
import uuid
import asyncio
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

# Import database functions and workflow
from mcp_server import (
    get_db,
    init_db,
    create_user,
    get_users,
    create_group,
    get_groups,
    add_group_member,
    create_receipt,
    add_line_item,
    add_line_item_split,
)
from app.workflow import ledger_workflow
from app.debt_simplification import simplify_debts
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from streamlit_mic_recorder import speech_to_text

# Load environment variables robustly
base_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(base_dir, "app", ".env")
load_dotenv(env_path)
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")

# Initialize Gemini Client if API key is present
client = None
if GOOGLE_API_KEY:
    client = genai.Client(api_key=GOOGLE_API_KEY)

# Ensure the database columns exist
def ensure_db_columns():
    conn = get_db()
    try:
        conn.execute("ALTER TABLE line_items ADD COLUMN category TEXT DEFAULT 'Food'")
        conn.commit()
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE groups ADD COLUMN budget REAL DEFAULT 0.0")
        conn.commit()
    except sqlite3.OperationalError:
        pass
    finally:
        conn.close()

# Initialize database and columns
init_db()
ensure_db_columns()

# Helper to delete a group
def delete_group(group_id):
    conn = get_db()
    try:
        conn.execute("DELETE FROM groups WHERE id = ?", (group_id,))
        conn.commit()
    finally:
        conn.close()

# Set page config
st.set_page_config(
    page_title="LedgerAgent",
    page_icon="🧾",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom premium styling
st.markdown("""
<style>
    .reportview-container {
        background: #0e1117;
    }
    .metric-card {
        background-color: #1e222b;
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        border: 1px solid #2d3139;
        text-align: center;
    }
    .metric-value {
        font-size: 28px;
        font-weight: bold;
        color: #00ffd0;
        margin-top: 5px;
    }
    .metric-label {
        font-size: 14px;
        color: #8a909d;
        text-transform: uppercase;
        letter-spacing: 1px;
    }
</style>
""", unsafe_allow_html=True)

st.title("🧾 LedgerAgent")
st.caption("AI-Powered Expense Tracker")

# Sidebar for App/Trip Management
st.sidebar.header("📁 Manage trips")

# Fetch current groups/trips
groups = get_groups()
group_names = [g['name'] for g in groups]

selected_group_name = st.sidebar.selectbox("Select Active Trip/Group", group_names if group_names else ["No Groups Available"])

# Trip manipulation controls
st.sidebar.markdown("---")
st.sidebar.subheader("Add/Delete Trips")
new_trip_name = st.sidebar.text_input("New Trip Name", placeholder="e.g. United States 2026")
add_trip_btn = st.sidebar.button("Add New Trip", use_container_width=True)

if add_trip_btn and new_trip_name:
    if new_trip_name in group_names:
        st.sidebar.warning(f"Trip '{new_trip_name}' already exists.")
    else:
        create_group(new_trip_name)
        st.sidebar.success(f"Trip '{new_trip_name}' created!")
        st.rerun()

st.sidebar.markdown("---")
if group_names:
    selected_group_id = next(g['id'] for g in groups if g['name'] == selected_group_name)
    delete_trip_btn = st.sidebar.button("🗑️ Remove Selected Trip", type="primary", use_container_width=True)
    if delete_trip_btn:
        delete_group(selected_group_id)
        st.sidebar.success(f"Trip '{selected_group_name}' removed.")
        st.rerun()

# Initialize session states
if "raw_line_items" not in st.session_state:
    st.session_state["raw_line_items"] = []
if "processed_result" not in st.session_state:
    st.session_state["processed_result"] = None
if "simplified_debts" not in st.session_state:
    st.session_state["simplified_debts"] = []

# Define tabs
tab1, tab2 = st.tabs(["🧾 New Expense", "📊 Dashboard"])

# Pydantic schemas for structured extraction
class ReceiptItem(BaseModel):
    item_name: str = Field(description="Name of the parsed item on the receipt")
    quantity: int = Field(description="Quantity of the item purchased")
    price: float = Field(description="Unit price of the item")
    total: float = Field(description="Total cost for this item")

class ReceiptData(BaseModel):
    items: list[ReceiptItem] = Field(description="A structured list of all parsed items on the receipt")

class AllocatedItem(BaseModel):
    item: str = Field(description="Name of the item")
    price: float = Field(description="Price or share of the cost for this allocation")
    assigned_person: str = Field(description="Name of the person assigned to this share")
    category: str = Field(description="Category of the item (e.g. Food, Transport, Attractions)")

class AllocationList(BaseModel):
    items: list[AllocatedItem] = Field(description="List of allocated line item shares")


# TAB 1: HITL Interactive Split
with tab1:
    st.subheader("Expense Split")
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        payer = st.text_input("Who paid the bill?", value="Alice", help="Name of the person who paid.")
        total_bill = st.number_input("Total Bill Amount ($)", min_value=0.0, value=0.0, step=0.01)
        receipt_file = st.file_uploader("Upload Receipt Image", type=["png", "jpg", "jpeg"])
        
    with col2:
        st.write("🎙️ Speak your splitting logic:")
        # Voice input widget
        voice_text = speech_to_text(
            language='en',
            start_prompt="Record Split Logic",
            stop_prompt="Stop Recording",
            just_once=True,
            key='voice_input'
        )
        
        if voice_text:
            st.success(f"Transcribed: '{voice_text}'")
            
        instructions = st.text_area(
            "Describe the splitting logic (or edit transcribed speech):",
            value=voice_text if voice_text else "Split everything equally between Alice, Bob, and Charlie.",
            height=120
        )
        
        # Default to selected trip in sidebar
        st.write(f"Saving to Trip: **{selected_group_name}**")

    process_btn = st.button("⚡ Process Receipt & Split", type="primary")
    
    if process_btn:
        if not client:
            st.error(f"GOOGLE_API_KEY not configured in environment. File checked: {env_path}")
        else:
            with st.spinner("AI parsing receipt image and allocating items..."):
                try:
                    receipt_items_json = ""
                    # If receipt image is uploaded, parse using Vision agent first
                    if receipt_file:
                        image_bytes = receipt_file.read()
                        mime_type = receipt_file.type
                        
                        vision_response = client.models.generate_content(
                            model='gemini-3.5-flash',
                            contents=[
                                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                                "Parse all line items with names, quantities, unit prices, and totals from this receipt."
                            ],
                            config=types.GenerateContentConfig(
                                response_mime_type="application/json",
                                response_schema=ReceiptData,
                            ),
                        )
                        receipt_items_json = vision_response.text
                    
                    # Run allocation allocation reasoning
                    alloc_prompt = f"""
                    Receipt Items Context (JSON):
                    {receipt_items_json if receipt_items_json else "No receipt image uploaded."}
                    
                    Payer: {payer}
                    Total Bill Amount: {total_bill}
                    User Splitting Instructions: {instructions}
                    
                    Map each item to the correct person based on splitting instructions.
                    If items are shared or split (e.g. 'split the rest equally'), generate separate line entries with the split share amount for each person.
                    Provide a category for each item matching 'Food', 'Transport', or 'Attractions' (or fallback to 'Food').
                    """
                    
                    alloc_response = client.models.generate_content(
                        model='gemini-3.5-flash',
                        contents=alloc_prompt,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=AllocationList,
                        )
                    )
                    
                    import json
                    parsed_allocations = json.loads(alloc_response.text).get("items", [])
                    st.session_state["raw_line_items"] = parsed_allocations
                    st.success("Successfully processed receipt items!")
                except Exception as e:
                    st.error(f"Error during AI processing: {e}")

    # Human-in-the-Loop editor
    if st.session_state["raw_line_items"]:
        st.markdown("---")
        st.subheader("✏️ Review & Adjust Line Item Allocations (Human-in-the-Loop)")
        st.write("Double check the assignments, prices, and categories below before confirming.")
        
        df_items = pd.DataFrame(st.session_state["raw_line_items"])
        # Ensure correct column headers and types
        if not df_items.empty:
            edited_df = st.data_editor(
                df_items,
                column_config={
                    "item": st.column_config.TextColumn("Item Name"),
                    "price": st.column_config.NumberColumn("Price/Share ($)", format="$%.2f"),
                    "assigned_person": st.column_config.TextColumn("Assigned Person"),
                    "category": st.column_config.SelectboxColumn(
                        "Category",
                        options=["Food", "Transport", "Attractions"]
                    )
                },
                num_rows="dynamic",
                key="hitl_editor"
            )
            
            confirm_btn = st.button("💾 Confirm & Save split", type="primary")
            
            if confirm_btn:
                if not group_names:
                    st.error("No active trip. Please create a trip/group in the sidebar first.")
                else:
                    with st.spinner("Saving splits and calculating net balances..."):
                        try:
                            # 1. Fetch group ID
                            group_id = selected_group_id
                            
                            # 2. Fetch or create users, add to group
                            unique_people = set(edited_df["assigned_person"].unique())
                            unique_people.add(payer)
                            
                            users_map = {}
                            existing_users = get_users()
                            for u in existing_users:
                                users_map[u['name']] = u['id']
                                
                            for person in unique_people:
                                if person not in users_map:
                                    user_res = create_user(person)
                                    if "ID" in user_res:
                                        uid = int(user_res.split("ID")[-1].replace(".", "").strip())
                                        users_map[person] = uid
                                    else:
                                        # Fallback retrieve again
                                        for u in get_users():
                                            if u['name'] == person:
                                                users_map[person] = u['id']
                                
                                # Add to group member
                                add_group_member(group_id, users_map[person])
                                
                            # 3. Create Receipt
                            payer_id = users_map[payer]
                            receipt_title = f"{selected_group_name} Split"
                            receipt_res = create_receipt(group_id, payer_id, receipt_title, total_bill)
                            receipt_id = int(receipt_res.split("ID")[-1].replace(".", "").strip())
                            
                            # 4. Save items & splits
                            # Calculate net balances directly for simplify debts
                            balances = {name: 0.0 for name in unique_people}
                            
                            # Payer paid the total
                            balances[payer] += total_bill
                            
                            for _, row in edited_df.iterrows():
                                item_name = row["item"]
                                item_price = float(row["price"])
                                person = row["assigned_person"]
                                item_cat = row["category"]
                                
                                # Write to DB
                                conn = get_db()
                                cursor = conn.cursor()
                                cursor.execute(
                                    "INSERT INTO line_items (receipt_id, title, price, category) VALUES (?, ?, ?, ?)",
                                    (receipt_id, item_name, item_price, item_cat)
                                )
                                line_item_id = cursor.lastrowid
                                conn.commit()
                                conn.close()
                                
                                add_line_item_split(line_item_id, users_map[person], item_price)
                                
                                # Subtract owed share from balance
                                balances[person] -= item_price
                                
                            # Simplify balances
                            simplified = simplify_debts(balances)
                            st.session_state["simplified_debts"] = simplified
                            
                            st.success("Splits committed to SQL database successfully!")
                        except Exception as e:
                            st.error(f"Error saving split: {e}")
                        
        if st.session_state["simplified_debts"]:
            st.markdown("### 💸 Final Debt Simplification Results")
            for debt in st.session_state["simplified_debts"]:
                st.markdown(f"* **{debt}**")


# TAB 2: Dashboard
with tab2:
    if not group_names:
        st.info("Please create a trip/group in the sidebar to view the dashboard.")
    else:
        st.subheader(f"📊 {selected_group_name} Dashboard")
        
        # Query database stats filtered by selected group/trip
        conn = get_db()
        
        # Fetch current budget from groups table
        cursor = conn.cursor()
        cursor.execute("SELECT budget FROM groups WHERE id = ?", (selected_group_id,))
        group_row = cursor.fetchone()
        current_budget = group_row[0] if group_row and group_row[0] is not None else 0.0
        
        # Budget input from user
        budget = st.number_input(
            "Set Trip Budget ($)", 
            min_value=0.0, 
            value=float(current_budget), 
            step=50.0, 
            key=f"budget_input_{selected_group_id}"
        )
        
        # Save budget changes to database
        if budget != current_budget:
            conn.execute("UPDATE groups SET budget = ? WHERE id = ?", (budget, selected_group_id))
            conn.commit()
            st.rerun()
            
        cursor.execute("SELECT SUM(total_amount) FROM receipts WHERE group_id = ?", (selected_group_id,))
        total_spent_row = cursor.fetchone()
        total_spent = total_spent_row[0] if total_spent_row and total_spent_row[0] is not None else 0.0
        remaining = budget - total_spent
        
        col_b1, col_b2, col_b3 = st.columns(3)
        with col_b1:
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-label">Total Trip Budget</div>
                <div class="metric-value">${budget:,.2f}</div>
            </div>
            """, unsafe_allow_html=True)
        with col_b2:
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-label">Amount Spent</div>
                <div class="metric-value" style="color: #ff4b4b;">${total_spent:,.2f}</div>
            </div>
            """, unsafe_allow_html=True)
        with col_b3:
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-label">Amount Remaining</div>
                <div class="metric-value" style="color: #00ffd0;">${remaining:,.2f}</div>
            </div>
            """, unsafe_allow_html=True)
            
        st.markdown("---")
        
        # Spend per person data query
        df_person = pd.read_sql_query("""
            SELECT u.name as Person, SUM(r.total_amount) as TotalSpend
            FROM receipts r
            JOIN users u ON r.payer_id = u.id
            WHERE r.group_id = ?
            GROUP BY u.name
        """, conn, params=(selected_group_id,))
        
        # Spend by category data query
        df_category = pd.read_sql_query("""
            SELECT category as Category, SUM(price) as TotalSpend
            FROM line_items li
            JOIN receipts r ON li.receipt_id = r.id
            WHERE r.group_id = ?
            GROUP BY category
        """, conn, params=(selected_group_id,))
        
        # Daily timeline spending query
        df_timeline = pd.read_sql_query("""
            SELECT DATE(r.created_at) as Date, SUM(r.total_amount) as DailySpend
            FROM receipts r
            WHERE r.group_id = ?
            GROUP BY DATE(r.created_at)
            ORDER BY Date ASC
        """, conn, params=(selected_group_id,))
        
        conn.close()
        
        # Render charts
        c1, c2 = st.columns(2)
        with c1:
            if not df_person.empty:
                fig_person = px.pie(
                    df_person,
                    values="TotalSpend",
                    names="Person",
                    title="Total Spend per Person",
                    hole=0.4,
                    color_discrete_sequence=px.colors.sequential.Tealgrn
                )
                fig_person.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color="#e0e0e0")
                st.plotly_chart(fig_person, use_container_width=True)
            else:
                st.info("No personal spending data available for this trip yet.")
                
        with c2:
            if not df_category.empty:
                fig_cat = px.pie(
                    df_category,
                    values="TotalSpend",
                    names="Category",
                    title="Total Spend by Category",
                    hole=0.4,
                    color_discrete_sequence=px.colors.sequential.Mint
                )
                fig_cat.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color="#e0e0e0")
                st.plotly_chart(fig_cat, use_container_width=True)
            else:
                st.info("No category spending data available for this trip yet.")
                
        st.markdown("---")
        st.subheader("Daily Spendings")
        if not df_timeline.empty:
            fig_time = px.bar(
                df_timeline,
                x="Date",
                y="DailySpend",
                title="Total Spend per Day",
                labels={"DailySpend": "Spent ($)", "Date": "Date"},
                color_discrete_sequence=["#00ffd0"]
            )
            fig_time.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color="#e0e0e0")
            fig_time.update_xaxes(type='category')
            st.plotly_chart(fig_time, use_container_width=True)
        else:
            st.info("No daily spending timeline data available for this trip yet.")
