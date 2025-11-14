from __future__ import annotations
import sqlite3
import uuid
from datetime import datetime, date
from typing import List, Dict, Tuple

import pandas as pd
import streamlit as st

DB_PATH = "invoice.db"

# ------------------------------ DB LAYER ------------------------------ #

def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_no TEXT UNIQUE,
                invoice_date TEXT,
                customer_name TEXT,
                customer_email TEXT,
                customer_phone TEXT,
                billing_address TEXT,
                subtotal REAL,
                discount_amount REAL,
                tax_rate REAL,
                tax_amount REAL,
                total REAL,
                notes TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id INTEGER,
                description TEXT,
                quantity REAL,
                unit_price REAL,
                line_total REAL,
                FOREIGN KEY(invoice_id) REFERENCES invoices(id) ON DELETE CASCADE
            )
            """
        )
        conn.commit()


# ------------------------------ HELPERS ------------------------------ #

def money(x: float | int) -> float:
    """Round to 2 decimals consistently."""
    return float(round((x or 0.0) + 0.0000001, 2))


def new_invoice_number(prefix: str = "INV") -> str:
    today = datetime.now().strftime("%Y%m%d")
    short = uuid.uuid4().hex[:6].upper()
    return f"{prefix}-{today}-{short}"


def compute_totals(items: List[Dict], discount: float, tax_rate: float) -> Tuple[float, float, float]:
    subtotal = money(sum((i.get("quantity", 0) or 0) * (i.get("unit_price", 0) or 0) for i in items))
    discount_amount = money(min(max(discount or 0.0, 0.0), subtotal))
    taxable = max(subtotal - discount_amount, 0.0)
    tax_amount = money(taxable * (tax_rate or 0.0) / 100.0)
    total = money(taxable + tax_amount)
    return subtotal, tax_amount, total


def upsert_invoice(
    invoice_no: str,
    invoice_date: str,
    customer_name: str,
    customer_email: str,
    customer_phone: str,
    billing_address: str,
    items: List[Dict],
    discount_amount: float,
    tax_rate: float,
    notes: str,
) -> int:
    subtotal, tax_amount, total = compute_totals(items, discount_amount, tax_rate)
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO invoices (
                invoice_no, invoice_date, customer_name, customer_email, customer_phone, billing_address,
                subtotal, discount_amount, tax_rate, tax_amount, total, notes
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                invoice_no,
                invoice_date,
                customer_name.strip(),
                customer_email.strip(),
                customer_phone.strip(),
                billing_address.strip(),
                subtotal,
                discount_amount,
                tax_rate,
                tax_amount,
                total,
                notes.strip(),
            ),
        )
        invoice_id = cur.lastrowid
        for it in items:
            qty = float(it.get("quantity") or 0)
            price = float(it.get("unit_price") or 0)
            line_total = money(qty * price)
            cur.execute(
                """
                INSERT INTO items (invoice_id, description, quantity, unit_price, line_total)
                VALUES (?,?,?,?,?)
                """,
                (invoice_id, str(it.get("description", "")).strip(), qty, price, line_total),
            )
        conn.commit()
        return invoice_id


def fetch_invoices_df() -> pd.DataFrame:
    with get_conn() as conn:
        df = pd.read_sql_query(
            """
            SELECT id, invoice_no, invoice_date, customer_name, customer_email, customer_phone,
                   subtotal, discount_amount, tax_rate, tax_amount, total, created_at
            FROM invoices
            ORDER BY datetime(invoice_date) DESC, id DESC
            """,
            conn,
        )
    return df


def fetch_invoice_full(invoice_id: int) -> Tuple[Dict, List[Dict]]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,))
        inv_row = cur.fetchone()
        cols = [d[0] for d in cur.description]
        invoice = dict(zip(cols, inv_row)) if inv_row else {}

        cur.execute(
            "SELECT description, quantity, unit_price, line_total FROM items WHERE invoice_id=?",
            (invoice_id,),
        )
        items = [
            {"description": r[0], "quantity": r[1], "unit_price": r[2], "line_total": r[3]}
            for r in cur.fetchall()
        ]
        return invoice, items


# ------------------------------ UI HELPERS ------------------------------ #

def invoice_html(invoice: Dict, items: List[Dict]) -> str:
    """Return a clean, printable HTML invoice."""
    styles = """
    <style>
    body { font-family: Arial, sans-serif; margin: 24px; }
    .header { display:flex; justify-content: space-between; align-items: flex-start; }
    .brand { font-size: 20px; font-weight: bold; }
    .muted { color:#666; }
    table { border-collapse: collapse; width: 100%; margin-top: 16px; }
    th, td { border: 1px solid #ddd; padding: 8px; }
    th { text-align:left; background: #f7f7f7; }
    .right { text-align: right; }
    .totals { width: 320px; margin-left: auto; }
    .footer { margin-top: 24px; font-size: 12px; color:#666; }
    .caps { text-transform: uppercase; letter-spacing: .06em; font-size: 12px; }
    .title { font-size: 24px; font-weight: 700; }
    .grid { display:grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 12px; }
    pre { white-space: pre-wrap; }
    </style>
    """

    rows = "".join(
        f"""
        <tr>
          <td>{i['description']}</td>
          <td class=right>{i['quantity']:.2f}</td>
          <td class=right>{i['unit_price']:.2f}</td>
          <td class=right>{i['line_total']:.2f}</td>
        </tr>
        """
        for i in items
    )

    html = f"""
    <!doctype html>
    <html><head><meta charset='utf-8'>{styles}</head>
    <body>
      <div class=header>
        <div>
          <div class=title>Invoice</div>
          <div class=muted>Invoice No: <strong>{invoice['invoice_no']}</strong></div>
          <div class=muted>Date: <strong>{invoice['invoice_date']}</strong></div>
        </div>
        <div class=brand>YOUR COMPANY<br><span class=muted>Address line 1<br>City, Country</span></div>
      </div>

      <div class=grid>
        <div>
          <div class=caps>Bill To</div>
          <div><strong>{invoice['customer_name'] or ''}</strong></div>
          <div class=muted>{invoice['customer_email'] or ''}</div>
          <div class=muted>{invoice['customer_phone'] or ''}</div>
          <pre>{invoice['billing_address'] or ''}</pre>
        </div>
        <div>
          <div class=caps>Notes</div>
          <pre>{invoice.get('notes') or ''}</pre>
        </div>
      </div>

      <table>
        <thead>
          <tr>
            <th>Description</th>
            <th class=right>Qty</th>
            <th class=right>Unit Price</th>
            <th class=right>Line Total</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>

      <table class=totals>
        <tr><td>Subtotal</td><td class=right>{invoice['subtotal']:.2f}</td></tr>
        <tr><td>Discount</td><td class=right>{invoice['discount_amount']:.2f}</td></tr>
        <tr><td>Tax Rate</td><td class=right>{invoice['tax_rate']:.2f}%</td></tr>
        <tr><td>Tax Amount</td><td class=right>{invoice['tax_amount']:.2f}</td></tr>
        <tr><th>Total</th><th class=right>{invoice['total']:.2f}</th></tr>
      </table>

      <div class=footer>
        Thank you for your business.
      </div>
    </body></html>
    """
    return html


# ------------------------------ STREAMLIT APP ------------------------------ #

st.set_page_config(page_title="Invoice & Billing Generator", page_icon="🧾", layout="wide")
init_db()

st.title("🧾 Invoice & Billing Generator")

with st.sidebar:
    st.header("New Invoice")
    prefix = st.text_input("Invoice Prefix", value="INV", help="Used to generate invoice number")
    default_no = new_invoice_number(prefix)
    invoice_no = st.text_input("Invoice No", value=default_no)
    invoice_date = st.date_input("Invoice Date", value=date.today())

    st.subheader("Customer Details")
    customer_name = st.text_input("Customer Name")
    customer_email = st.text_input("Customer Email")
    customer_phone = st.text_input("Customer Phone")
    billing_address = st.text_area("Billing Address")

    st.subheader("Pricing")
    discount_amount = st.number_input("Discount amount", min_value=0.0, step=0.5, value=0.0)
    tax_rate = st.number_input("Tax rate (%)", min_value=0.0, step=0.5, value=0.0)

    notes = st.text_area("Notes (optional)")

st.markdown("---")

st.subheader("Line Items")

if "items" not in st.session_state:
    st.session_state["items"] = []



# Item entry form
with st.form("add_item_form", clear_on_submit=True):
    c1, c2, c3, c4, c5 = st.columns([4, 1, 2, 2, 1])
    with c1:
        desc = st.text_input("Description", key="desc")
    with c2:
        qty = st.number_input("Qty", min_value=0.0, step=1.0, value=1.0, key="qty")
    with c3:
        unit = st.number_input("Unit Price", min_value=0.0, step=1.0, value=0.0, key="unit")
    with c4:
        st.markdown("**Line Total**")
        st.write(money(qty * unit))
    with c5:
        st.write("")
        add_clicked = st.form_submit_button("Add ➕")

    if add_clicked:
        st.session_state["items"].append({
            "description": desc,
            "quantity": qty,
            "unit_price": unit,
        })

# Items table with remove buttons
if st.session_state["items"]:
    df_items = pd.DataFrame(st.session_state["items"])
    df_items["line_total"] = df_items["quantity"] * df_items["unit_price"]
    df_items["line_total"] = df_items["line_total"].apply(money)

    st.dataframe(
        df_items.rename(columns={"description": "Description", "quantity": "Qty", "unit_price": "Unit Price", "line_total": "Line Total"}),
        use_container_width=True,
    )

    # Remove item controls
    idxs = list(range(len(st.session_state["items"])))
    rm_idx = st.selectbox("Remove item (select index)", options=["-"] + idxs, index=0)
    if rm_idx != "-":
        if st.button("Remove selected"):
            st.session_state["items"].pop(int(rm_idx))
            st.rerun()

subtotal, tax_amount, total = compute_totals(st.session_state["items"], discount_amount, tax_rate)

c1, c2, c3, c4 = st.columns(4)
with c1:
    st.metric("Subtotal", f"{subtotal:.2f}")
with c2:
    st.metric("Discount", f"{money(discount_amount):.2f}")
with c3:
    st.metric("Tax", f"{tax_amount:.2f} ({tax_rate:.2f}%)")
with c4:
    st.metric("Total", f"{total:.2f}")

colA, colB = st.columns([1, 1])
with colA:
    if st.button("💾 Save Invoice", type="primary", use_container_width=True):
        if not st.session_state["items"]:
            st.error("Add at least one line item before saving.")
        else:
            try:
                invoice_id = upsert_invoice(
                    invoice_no=invoice_no,
                    invoice_date=str(invoice_date),
                    customer_name=customer_name,
                    customer_email=customer_email,
                    customer_phone=customer_phone,
                    billing_address=billing_address,
                    items=st.session_state["items"],
                    discount_amount=discount_amount,
                    tax_rate=tax_rate,
                    notes=notes,
                )
                st.success(f"Saved invoice #{invoice_no} (ID {invoice_id}).")
                # Reset line items for a fresh start
                st.session_state["items"] = []
            except sqlite3.IntegrityError:
                st.error("Invoice number already exists. Please change it and try again.")

with colB:
    if st.button("🧹 Reset Form", use_container_width=True):
        st.session_state["items"] = []
        st.rerun()

st.markdown("---")

st.header("📚 All Invoices")

# Filters
f1, f2, f3, f4 = st.columns(4)
with f1:
    q = st.text_input("Search text (number, customer, email)")
with f2:
    from_dt = st.date_input("From date", value=None, key="from_dt")
with f3:
    to_dt = st.date_input("To date", value=None, key="to_dt")
with f4:
    st.write("")
    refresh = st.button("🔄 Refresh")

invoices_df = fetch_invoices_df()

if q:
    mask = (
        invoices_df["invoice_no"].str.contains(q, case=False, na=False)
        | invoices_df["customer_name"].str.contains(q, case=False, na=False)
        | invoices_df["customer_email"].str.contains(q, case=False, na=False)
        | invoices_df["customer_phone"].str.contains(q, case=False, na=False)
    )
    invoices_df = invoices_df[mask]

if from_dt:
    invoices_df = invoices_df[pd.to_datetime(invoices_df["invoice_date"]) >= pd.to_datetime(from_dt)]
if to_dt:
    invoices_df = invoices_df[pd.to_datetime(invoices_df["invoice_date"]) <= pd.to_datetime(to_dt)]

st.dataframe(invoices_df, use_container_width=True)

# Export CSV
csv_col1, csv_col2 = st.columns([1, 3])
with csv_col1:
    if not invoices_df.empty:
        csv = invoices_df.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Export CSV", data=csv, file_name="invoices_export.csv", mime="text/csv")

# View selected invoice
st.subheader("🔍 View Invoice")
sel_id = st.selectbox("Choose Invoice ID", options=["-"] + invoices_df["id"].astype(int).astype(str).tolist(), index=0)
if sel_id != "-":
    inv_id_int = int(sel_id)
    invoice, items = fetch_invoice_full(inv_id_int)
    if invoice:
        st.write({k: invoice[k] for k in ["invoice_no", "invoice_date", "customer_name", "total"]})
        html = invoice_html(invoice, items)
        st.download_button(
            "⬇️ Download HTML Invoice",
            data=html.encode("utf-8"),
            file_name=f"{invoice['invoice_no']}.html",
            mime="text/html",
        )
        with st.expander("Preview invoice"):
            st.components.v1.html(html, height=700, scrolling=True)
    else:
        st.info("Invoice not found.")

st.markdown("---")

st.caption(
    "Pro tip: Keep regular backups of `invoice.db`. You can also copy this file to another machine to migrate all your saved bills."
)
