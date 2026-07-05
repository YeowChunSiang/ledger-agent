import sqlite3
import os
from typing import List, Dict, Optional
from mcp.server.fastmcp import FastMCP

# Initialize FastMCP Server
mcp = FastMCP("Ledger Assistant DB")

DB_PATH = "ledger.db"
SCHEMA_PATH = "schema.sql"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    # Always ensure db is initialized
    with sqlite3.connect(DB_PATH) as conn:
        with open(SCHEMA_PATH, "r") as f:
            conn.executescript(f.read())
        conn.commit()

init_db()

@mcp.tool()
def create_user(name: str, email: str = None) -> str:
    """Create a new user.

    Args:
        name: Unique name of the user.
        email: Optional email address.
    """
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (name, email) VALUES (?, ?)", (name, email))
        conn.commit()
        return f"User '{name}' created with ID {cursor.lastrowid}."
    except sqlite3.IntegrityError:
        return f"User '{name}' or email already exists."
    except Exception as e:
        return f"Error: {e}"
    finally:
        conn.close()

@mcp.tool()
def get_users() -> List[Dict]:
    """Retrieve all users in the system."""
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, email FROM users")
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

@mcp.tool()
def create_group(name: str) -> str:
    """Create a new group for splitting bills.

    Args:
        name: Name of the group.
    """
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO groups (name) VALUES (?)", (name,))
        conn.commit()
        return f"Group '{name}' created with ID {cursor.lastrowid}."
    except Exception as e:
        return f"Error: {e}"
    finally:
        conn.close()

@mcp.tool()
def add_group_member(group_id: int, user_id: int) -> str:
    """Add a user to a group.

    Args:
        group_id: ID of the group.
        user_id: ID of the user.
    """
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO group_members (group_id, user_id) VALUES (?, ?)", (group_id, user_id))
        conn.commit()
        return f"Added user {user_id} to group {group_id}."
    except sqlite3.IntegrityError:
        return f"User {user_id} is already a member of group {group_id} or one of the IDs is invalid."
    except Exception as e:
        return f"Error: {e}"
    finally:
        conn.close()

@mcp.tool()
def create_receipt(group_id: int, payer_id: int, title: str, total_amount: float) -> str:
    """Create a new receipt for a transaction.

    Args:
        group_id: ID of the group the receipt belongs to.
        payer_id: ID of the user who paid for the receipt.
        title: Title/description of the receipt.
        total_amount: Total amount paid.
    """
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO receipts (group_id, payer_id, title, total_amount) VALUES (?, ?, ?, ?)",
            (group_id, payer_id, title, total_amount)
        )
        conn.commit()
        return f"Receipt '{title}' created with ID {cursor.lastrowid}."
    except sqlite3.IntegrityError:
        return "Invalid group_id or payer_id."
    except Exception as e:
        return f"Error: {e}"
    finally:
        conn.close()

@mcp.tool()
def add_line_item(receipt_id: int, title: str, price: float) -> str:
    """Add a specific line item to a receipt.

    Args:
        receipt_id: ID of the receipt.
        title: Description of the item.
        price: Cost of the item.
    """
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO line_items (receipt_id, title, price) VALUES (?, ?, ?)",
            (receipt_id, title, price)
        )
        conn.commit()
        return f"Line item '{title}' created with ID {cursor.lastrowid}."
    except sqlite3.IntegrityError:
        return "Invalid receipt_id."
    except Exception as e:
        return f"Error: {e}"
    finally:
        conn.close()

@mcp.tool()
def add_line_item_split(line_item_id: int, user_id: int, share: float) -> str:
    """Assign a user's share for a specific line item.

    Args:
        line_item_id: ID of the line item.
        user_id: ID of the user.
        share: The cost/share the user owes for this item.
    """
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO line_item_splits (line_item_id, user_id, share) VALUES (?, ?, ?)",
            (line_item_id, user_id, share)
        )
        conn.commit()
        return f"Assigned split of {share} for user {user_id} on line item {line_item_id}."
    except sqlite3.IntegrityError:
        return "Invalid line_item_id, user_id, or split already exists."
    except Exception as e:
        return f"Error: {e}"
    finally:
        conn.close()

@mcp.tool()
def get_group_balances(group_id: int) -> str:
    """Calculate and return the net balances for all members of a group.
    
    A positive balance means the group owes them money (they are a net lender).
    A negative balance means they owe the group money (they are a net borrower).
    """
    conn = get_db()
    try:
        cursor = conn.cursor()
        
        # Get all members of the group
        cursor.execute(
            "SELECT u.id, u.name FROM users u JOIN group_members gm ON u.id = gm.user_id WHERE gm.group_id = ?",
            (group_id,)
        )
        members = {row['id']: {'name': row['name'], 'paid': 0.0, 'owed': 0.0} for row in cursor.fetchall()}
        
        if not members:
            return "No members found in group."
            
        # Calculate total paid by each user in the group
        cursor.execute(
            "SELECT payer_id, SUM(total_amount) as total_paid FROM receipts WHERE group_id = ? GROUP BY payer_id",
            (group_id,)
        )
        for row in cursor.fetchall():
            if row['payer_id'] in members:
                members[row['payer_id']]['paid'] = row['total_paid']
                
        # Calculate total owed by each user across all line item splits on receipts in this group
        cursor.execute(
            """
            SELECT lis.user_id, SUM(lis.share) as total_owed 
            FROM line_item_splits lis
            JOIN line_items li ON lis.line_item_id = li.id
            JOIN receipts r ON li.receipt_id = r.id
            WHERE r.group_id = ?
            GROUP BY lis.user_id
            """,
            (group_id,)
        )
        for row in cursor.fetchall():
            if row['user_id'] in members:
                members[row['user_id']]['owed'] = row['total_owed']
                
        # Format results
        output = [f"Balances for Group ID {group_id}:"]
        for uid, data in members.items():
            net = data['paid'] - data['owed']
            output.append(
                f"- {data['name']} (ID: {uid}): Paid: ${data['paid']:.2f}, Owed: ${data['owed']:.2f}, Net: ${net:+.2f}"
            )
            
        return "\n".join(output)
    except Exception as e:
        return f"Error calculating balances: {e}"
    finally:
        conn.close()

@mcp.tool()
def get_groups() -> List[Dict]:
    """Retrieve all existing groups in the system, returning their ID and name."""
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM groups")
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

if __name__ == "__main__":
    mcp.run()
