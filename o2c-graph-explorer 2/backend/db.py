"""
Data Ingestion & SQLite Setup for SAP Order-to-Cash Graph System
=================================================================

Reads all JSONL files from the dataset directory, flattens nested fields,
creates normalized SQLite tables, and builds indexes on foreign keys.

Usage:
    python db.py                         # Uses default paths
    python db.py --data-dir ./sap-o2c-data --db-path ./data/o2c.db

Output: SQLite database with 15 core tables + indexes on all FK columns.
"""

import json
import glob
import sqlite3
import os
import argparse
from pathlib import Path


# ==============================================================================
# TABLE DEFINITIONS
# ==============================================================================
# Each entry: (sqlite_table_name, source_directory_name, CREATE TABLE SQL)
# We define explicit schemas rather than auto-inferring to ensure correct types
# and to drop noisy columns that add no query value.

TABLE_DEFINITIONS = [
    (
        "customers",
        "business_partners",
        """CREATE TABLE IF NOT EXISTS customers (
            businessPartner TEXT PRIMARY KEY,
            customer TEXT,
            businessPartnerCategory TEXT,
            businessPartnerFullName TEXT,
            businessPartnerName TEXT,
            businessPartnerGrouping TEXT,
            createdByUser TEXT,
            creationDate TEXT,
            creationTime TEXT,
            firstName TEXT,
            lastName TEXT,
            organizationBpName1 TEXT,
            organizationBpName2 TEXT,
            industry TEXT,
            lastChangeDate TEXT,
            businessPartnerIsBlocked INTEGER,
            isMarkedForArchiving INTEGER
        )"""
    ),
    (
        "customer_addresses",
        "business_partner_addresses",
        """CREATE TABLE IF NOT EXISTS customer_addresses (
            businessPartner TEXT,
            addressId TEXT,
            cityName TEXT,
            country TEXT,
            postalCode TEXT,
            region TEXT,
            streetName TEXT,
            addressTimeZone TEXT,
            FOREIGN KEY (businessPartner) REFERENCES customers(businessPartner)
        )"""
    ),
    (
        "customer_company_assignments",
        "customer_company_assignments",
        """CREATE TABLE IF NOT EXISTS customer_company_assignments (
            customer TEXT,
            companyCode TEXT,
            reconciliationAccount TEXT,
            paymentTerms TEXT,
            paymentMethodsList TEXT,
            customerAccountGroup TEXT,
            deletionIndicator INTEGER,
            FOREIGN KEY (customer) REFERENCES customers(businessPartner)
        )"""
    ),
    (
        "customer_sales_area_assignments",
        "customer_sales_area_assignments",
        """CREATE TABLE IF NOT EXISTS customer_sales_area_assignments (
            customer TEXT,
            salesOrganization TEXT,
            distributionChannel TEXT,
            division TEXT,
            currency TEXT,
            customerPaymentTerms TEXT,
            deliveryPriority TEXT,
            incotermsClassification TEXT,
            incotermsLocation1 TEXT,
            shippingCondition TEXT,
            FOREIGN KEY (customer) REFERENCES customers(businessPartner)
        )"""
    ),
    (
        "sales_order_headers",
        "sales_order_headers",
        """CREATE TABLE IF NOT EXISTS sales_order_headers (
            salesOrder TEXT PRIMARY KEY,
            salesOrderType TEXT,
            salesOrganization TEXT,
            distributionChannel TEXT,
            organizationDivision TEXT,
            salesGroup TEXT,
            salesOffice TEXT,
            soldToParty TEXT,
            creationDate TEXT,
            createdByUser TEXT,
            lastChangeDateTime TEXT,
            totalNetAmount REAL,
            overallDeliveryStatus TEXT,
            overallOrdReltdBillgStatus TEXT,
            overallSdDocReferenceStatus TEXT,
            transactionCurrency TEXT,
            pricingDate TEXT,
            requestedDeliveryDate TEXT,
            headerBillingBlockReason TEXT,
            deliveryBlockReason TEXT,
            incotermsClassification TEXT,
            incotermsLocation1 TEXT,
            customerPaymentTerms TEXT,
            totalCreditCheckStatus TEXT,
            FOREIGN KEY (soldToParty) REFERENCES customers(businessPartner)
        )"""
    ),
    (
        "sales_order_items",
        "sales_order_items",
        """CREATE TABLE IF NOT EXISTS sales_order_items (
            salesOrder TEXT,
            salesOrderItem TEXT,
            salesOrderItemCategory TEXT,
            material TEXT,
            requestedQuantity REAL,
            requestedQuantityUnit TEXT,
            transactionCurrency TEXT,
            netAmount REAL,
            materialGroup TEXT,
            productionPlant TEXT,
            storageLocation TEXT,
            salesDocumentRjcnReason TEXT,
            itemBillingBlockReason TEXT,
            PRIMARY KEY (salesOrder, salesOrderItem),
            FOREIGN KEY (salesOrder) REFERENCES sales_order_headers(salesOrder),
            FOREIGN KEY (material) REFERENCES products(product),
            FOREIGN KEY (productionPlant) REFERENCES plants(plant)
        )"""
    ),
    (
        "sales_order_schedule_lines",
        "sales_order_schedule_lines",
        """CREATE TABLE IF NOT EXISTS sales_order_schedule_lines (
            salesOrder TEXT,
            salesOrderItem TEXT,
            scheduleLine TEXT,
            confirmedDeliveryDate TEXT,
            orderQuantityUnit TEXT,
            confdOrderQtyByMatlAvailCheck REAL,
            PRIMARY KEY (salesOrder, salesOrderItem, scheduleLine),
            FOREIGN KEY (salesOrder, salesOrderItem) REFERENCES sales_order_items(salesOrder, salesOrderItem)
        )"""
    ),
    (
        "outbound_delivery_headers",
        "outbound_delivery_headers",
        """CREATE TABLE IF NOT EXISTS outbound_delivery_headers (
            deliveryDocument TEXT PRIMARY KEY,
            creationDate TEXT,
            creationTime TEXT,
            actualGoodsMovementDate TEXT,
            actualGoodsMovementTime TEXT,
            overallGoodsMovementStatus TEXT,
            overallPickingStatus TEXT,
            overallProofOfDeliveryStatus TEXT,
            deliveryBlockReason TEXT,
            headerBillingBlockReason TEXT,
            hdrGeneralIncompletionStatus TEXT,
            shippingPoint TEXT,
            lastChangeDate TEXT
        )"""
    ),
    (
        "outbound_delivery_items",
        "outbound_delivery_items",
        """CREATE TABLE IF NOT EXISTS outbound_delivery_items (
            deliveryDocument TEXT,
            deliveryDocumentItem TEXT,
            actualDeliveryQuantity REAL,
            deliveryQuantityUnit TEXT,
            batch TEXT,
            plant TEXT,
            referenceSdDocument TEXT,
            referenceSdDocumentItem TEXT,
            storageLocation TEXT,
            itemBillingBlockReason TEXT,
            lastChangeDate TEXT,
            PRIMARY KEY (deliveryDocument, deliveryDocumentItem),
            FOREIGN KEY (deliveryDocument) REFERENCES outbound_delivery_headers(deliveryDocument),
            FOREIGN KEY (referenceSdDocument) REFERENCES sales_order_headers(salesOrder),
            FOREIGN KEY (plant) REFERENCES plants(plant)
        )"""
    ),
    (
        "billing_document_headers",
        "billing_document_headers",
        """CREATE TABLE IF NOT EXISTS billing_document_headers (
            billingDocument TEXT PRIMARY KEY,
            billingDocumentType TEXT,
            creationDate TEXT,
            creationTime TEXT,
            lastChangeDateTime TEXT,
            billingDocumentDate TEXT,
            billingDocumentIsCancelled INTEGER,
            cancelledBillingDocument TEXT,
            totalNetAmount REAL,
            transactionCurrency TEXT,
            companyCode TEXT,
            fiscalYear TEXT,
            accountingDocument TEXT,
            soldToParty TEXT,
            FOREIGN KEY (soldToParty) REFERENCES customers(businessPartner)
        )"""
    ),
    (
        "billing_document_items",
        "billing_document_items",
        """CREATE TABLE IF NOT EXISTS billing_document_items (
            billingDocument TEXT,
            billingDocumentItem TEXT,
            material TEXT,
            billingQuantity REAL,
            billingQuantityUnit TEXT,
            netAmount REAL,
            transactionCurrency TEXT,
            referenceSdDocument TEXT,
            referenceSdDocumentItem TEXT,
            PRIMARY KEY (billingDocument, billingDocumentItem),
            FOREIGN KEY (billingDocument) REFERENCES billing_document_headers(billingDocument),
            FOREIGN KEY (referenceSdDocument) REFERENCES outbound_delivery_headers(deliveryDocument),
            FOREIGN KEY (material) REFERENCES products(product)
        )"""
    ),
    (
        "billing_document_cancellations",
        "billing_document_cancellations",
        """CREATE TABLE IF NOT EXISTS billing_document_cancellations (
            billingDocument TEXT PRIMARY KEY,
            billingDocumentType TEXT,
            creationDate TEXT,
            creationTime TEXT,
            lastChangeDateTime TEXT,
            billingDocumentDate TEXT,
            billingDocumentIsCancelled INTEGER,
            cancelledBillingDocument TEXT,
            totalNetAmount REAL,
            transactionCurrency TEXT,
            companyCode TEXT,
            fiscalYear TEXT,
            accountingDocument TEXT,
            soldToParty TEXT
        )"""
    ),
    (
        "journal_entries",
        "journal_entry_items_accounts_receivable",
        """CREATE TABLE IF NOT EXISTS journal_entries (
            companyCode TEXT,
            fiscalYear TEXT,
            accountingDocument TEXT,
            accountingDocumentItem TEXT,
            accountingDocumentType TEXT,
            glAccount TEXT,
            referenceDocument TEXT,
            costCenter TEXT,
            profitCenter TEXT,
            transactionCurrency TEXT,
            amountInTransactionCurrency REAL,
            companyCodeCurrency TEXT,
            amountInCompanyCodeCurrency REAL,
            postingDate TEXT,
            documentDate TEXT,
            assignmentReference TEXT,
            lastChangeDateTime TEXT,
            customer TEXT,
            financialAccountType TEXT,
            clearingDate TEXT,
            clearingAccountingDocument TEXT,
            clearingDocFiscalYear TEXT,
            PRIMARY KEY (companyCode, fiscalYear, accountingDocument, accountingDocumentItem),
            FOREIGN KEY (customer) REFERENCES customers(businessPartner)
        )"""
    ),
    (
        "payments",
        "payments_accounts_receivable",
        """CREATE TABLE IF NOT EXISTS payments (
            companyCode TEXT,
            fiscalYear TEXT,
            accountingDocument TEXT,
            accountingDocumentItem TEXT,
            clearingDate TEXT,
            clearingAccountingDocument TEXT,
            clearingDocFiscalYear TEXT,
            amountInTransactionCurrency REAL,
            transactionCurrency TEXT,
            amountInCompanyCodeCurrency REAL,
            companyCodeCurrency TEXT,
            customer TEXT,
            invoiceReference TEXT,
            invoiceReferenceFiscalYear TEXT,
            salesDocument TEXT,
            salesDocumentItem TEXT,
            postingDate TEXT,
            documentDate TEXT,
            assignmentReference TEXT,
            glAccount TEXT,
            financialAccountType TEXT,
            profitCenter TEXT,
            costCenter TEXT,
            PRIMARY KEY (companyCode, fiscalYear, accountingDocument, accountingDocumentItem),
            FOREIGN KEY (customer) REFERENCES customers(businessPartner)
        )"""
    ),
    (
        "products",
        "products",
        """CREATE TABLE IF NOT EXISTS products (
            product TEXT PRIMARY KEY,
            productType TEXT,
            crossPlantStatus TEXT,
            creationDate TEXT,
            createdByUser TEXT,
            lastChangeDate TEXT,
            isMarkedForDeletion INTEGER,
            productOldId TEXT,
            grossWeight REAL,
            weightUnit TEXT,
            netWeight REAL,
            productGroup TEXT,
            baseUnit TEXT,
            division TEXT,
            industrySector TEXT
        )"""
    ),
    (
        "product_descriptions",
        "product_descriptions",
        """CREATE TABLE IF NOT EXISTS product_descriptions (
            product TEXT,
            language TEXT,
            productDescription TEXT,
            PRIMARY KEY (product, language),
            FOREIGN KEY (product) REFERENCES products(product)
        )"""
    ),
    (
        "plants",
        "plants",
        """CREATE TABLE IF NOT EXISTS plants (
            plant TEXT PRIMARY KEY,
            plantName TEXT,
            valuationArea TEXT,
            plantCustomer TEXT,
            plantSupplier TEXT,
            factoryCalendar TEXT,
            salesOrganization TEXT,
            addressId TEXT,
            distributionChannel TEXT,
            division TEXT,
            language TEXT,
            isMarkedForArchiving INTEGER
        )"""
    ),
]

# Indexes on foreign key columns for fast joins
INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_so_headers_soldtoparty ON sales_order_headers(soldToParty)",
    "CREATE INDEX IF NOT EXISTS idx_so_items_salesorder ON sales_order_items(salesOrder)",
    "CREATE INDEX IF NOT EXISTS idx_so_items_material ON sales_order_items(material)",
    "CREATE INDEX IF NOT EXISTS idx_so_items_plant ON sales_order_items(productionPlant)",
    "CREATE INDEX IF NOT EXISTS idx_so_schedule_salesorder ON sales_order_schedule_lines(salesOrder)",
    "CREATE INDEX IF NOT EXISTS idx_del_items_delivery ON outbound_delivery_items(deliveryDocument)",
    "CREATE INDEX IF NOT EXISTS idx_del_items_refsd ON outbound_delivery_items(referenceSdDocument)",
    "CREATE INDEX IF NOT EXISTS idx_del_items_plant ON outbound_delivery_items(plant)",
    "CREATE INDEX IF NOT EXISTS idx_bill_headers_acctdoc ON billing_document_headers(accountingDocument)",
    "CREATE INDEX IF NOT EXISTS idx_bill_headers_soldto ON billing_document_headers(soldToParty)",
    "CREATE INDEX IF NOT EXISTS idx_bill_items_billing ON billing_document_items(billingDocument)",
    "CREATE INDEX IF NOT EXISTS idx_bill_items_refsd ON billing_document_items(referenceSdDocument)",
    "CREATE INDEX IF NOT EXISTS idx_bill_items_material ON billing_document_items(material)",
    "CREATE INDEX IF NOT EXISTS idx_journal_acctdoc ON journal_entries(accountingDocument)",
    "CREATE INDEX IF NOT EXISTS idx_journal_refdoc ON journal_entries(referenceDocument)",
    "CREATE INDEX IF NOT EXISTS idx_journal_customer ON journal_entries(customer)",
    "CREATE INDEX IF NOT EXISTS idx_journal_clearing ON journal_entries(clearingAccountingDocument)",
    "CREATE INDEX IF NOT EXISTS idx_payments_clearing ON payments(clearingAccountingDocument)",
    "CREATE INDEX IF NOT EXISTS idx_payments_customer ON payments(customer)",
    "CREATE INDEX IF NOT EXISTS idx_payments_acctdoc ON payments(accountingDocument)",
    "CREATE INDEX IF NOT EXISTS idx_prod_desc_product ON product_descriptions(product)",
    "CREATE INDEX IF NOT EXISTS idx_cust_addr_bp ON customer_addresses(businessPartner)",
]


# ==============================================================================
# DATA LOADING
# ==============================================================================

def flatten_time_field(obj: dict, field_name: str) -> str | None:
    """Convert {hours, minutes, seconds} dict to 'HH:MM:SS' string."""
    val = obj.get(field_name)
    if isinstance(val, dict):
        h = val.get("hours", 0)
        m = val.get("minutes", 0)
        s = val.get("seconds", 0)
        return f"{h:02d}:{m:02d}:{s:02d}"
    return val


def load_jsonl_files(directory: str) -> list[dict]:
    """Load all JSONL files from a directory, flatten nested time fields."""
    records = []
    files = sorted(glob.glob(os.path.join(directory, "*.jsonl")))
    for filepath in files:
        with open(filepath, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                # Flatten nested time dicts
                for key in list(obj.keys()):
                    if isinstance(obj[key], dict):
                        obj[key] = flatten_time_field(obj, key)
                    # Convert booleans to int for SQLite
                    if isinstance(obj[key], bool):
                        obj[key] = int(obj[key])
                records.append(obj)
    return records


def get_table_columns(conn: sqlite3.Connection, table_name: str) -> list[str]:
    """Get column names for a table from SQLite schema."""
    cursor = conn.execute(f"PRAGMA table_info({table_name})")
    return [row[1] for row in cursor.fetchall()]


def insert_records(conn: sqlite3.Connection, table_name: str, records: list[dict]):
    """Insert records into table, only using columns that exist in the schema."""
    if not records:
        return 0

    table_columns = set(get_table_columns(conn, table_name))

    # Filter each record to only include columns that exist in the table
    filtered = []
    for rec in records:
        row = {k: v for k, v in rec.items() if k in table_columns}
        filtered.append(row)

    # Use the union of all keys present across records
    all_keys = sorted(table_columns & set().union(*(r.keys() for r in filtered)))

    placeholders = ", ".join(["?"] * len(all_keys))
    columns = ", ".join(all_keys)
    sql = f"INSERT OR IGNORE INTO {table_name} ({columns}) VALUES ({placeholders})"

    rows_inserted = 0
    for row in filtered:
        values = [row.get(k) for k in all_keys]
        try:
            conn.execute(sql, values)
            rows_inserted += 1
        except sqlite3.IntegrityError:
            pass  # Skip duplicates

    return rows_inserted


# ==============================================================================
# MAIN BUILD FUNCTION
# ==============================================================================

def build_database(data_dir: str, db_path: str) -> dict:
    """
    Build the complete SQLite database from JSONL source files.
    
    Args:
        data_dir: Path to the sap-o2c-data directory containing entity subdirectories
        db_path: Output path for the SQLite database file
    
    Returns:
        Dict with table names and row counts
    """
    # Ensure output directory exists
    os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)

    # Remove existing database to rebuild fresh
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    stats = {}

    try:
        # Create all tables
        for table_name, _, create_sql in TABLE_DEFINITIONS:
            conn.execute(create_sql)
        conn.commit()

        # Load data into each table
        for table_name, source_dir, _ in TABLE_DEFINITIONS:
            source_path = os.path.join(data_dir, source_dir)
            if not os.path.isdir(source_path):
                print(f"  WARNING: Directory not found: {source_path}")
                stats[table_name] = 0
                continue

            records = load_jsonl_files(source_path)
            count = insert_records(conn, table_name, records)
            conn.commit()
            stats[table_name] = count
            print(f"  {table_name}: {count} rows loaded")

        # Create indexes
        print("\nCreating indexes...")
        for idx_sql in INDEXES:
            conn.execute(idx_sql)
        conn.commit()
        print(f"  {len(INDEXES)} indexes created")

        # Verify with counts
        print("\nVerification:")
        for table_name, _, _ in TABLE_DEFINITIONS:
            cursor = conn.execute(f"SELECT COUNT(*) FROM {table_name}")
            actual = cursor.fetchone()[0]
            print(f"  {table_name}: {actual} rows")

    finally:
        conn.close()

    return stats


# ==============================================================================
# GRAPH DATA EXPORT (for NetworkX / Cytoscape.js)
# ==============================================================================

def export_graph_data(db_path: str) -> dict:
    """
    Query the SQLite database and return nodes + edges for graph construction.
    Returns a dict with 'nodes' and 'edges' lists.
    
    This is used by:
    1. Backend: NetworkX graph construction (graph.py)
    2. Frontend: Cytoscape.js visualization (via /api/graph endpoint)
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    nodes = []
    edges = []

    try:
        # --- NODES ---

        # Customers
        for row in conn.execute("""
            SELECT c.businessPartner, c.businessPartnerFullName, ca.cityName, ca.country
            FROM customers c
            LEFT JOIN customer_addresses ca ON c.businessPartner = ca.businessPartner
        """):
            nodes.append({
                "id": f"CUST_{row['businessPartner']}",
                "type": "Customer",
                "label": row["businessPartnerFullName"] or row["businessPartner"],
                "data": dict(row),
            })

        # Sales Orders
        for row in conn.execute("""
            SELECT salesOrder, salesOrderType, soldToParty, creationDate,
                   totalNetAmount, overallDeliveryStatus, transactionCurrency
            FROM sales_order_headers
        """):
            nodes.append({
                "id": f"SO_{row['salesOrder']}",
                "type": "SalesOrder",
                "label": f"SO {row['salesOrder']}",
                "data": dict(row),
            })

        # Deliveries
        for row in conn.execute("""
            SELECT deliveryDocument, creationDate, overallGoodsMovementStatus, shippingPoint
            FROM outbound_delivery_headers
        """):
            nodes.append({
                "id": f"DEL_{row['deliveryDocument']}",
                "type": "Delivery",
                "label": f"DEL {row['deliveryDocument']}",
                "data": dict(row),
            })

        # Billing Documents
        for row in conn.execute("""
            SELECT billingDocument, billingDocumentType, billingDocumentDate,
                   totalNetAmount, billingDocumentIsCancelled, accountingDocument, soldToParty
            FROM billing_document_headers
        """):
            nodes.append({
                "id": f"BILL_{row['billingDocument']}",
                "type": "BillingDocument",
                "label": f"BILL {row['billingDocument']}",
                "data": dict(row),
            })

        # Journal Entries (deduplicated by accountingDocument)
        for row in conn.execute("""
            SELECT DISTINCT accountingDocument, accountingDocumentType, referenceDocument,
                   postingDate, customer,
                   SUM(amountInTransactionCurrency) as totalAmount
            FROM journal_entries
            GROUP BY accountingDocument
        """):
            nodes.append({
                "id": f"JE_{row['accountingDocument']}",
                "type": "JournalEntry",
                "label": f"JE {row['accountingDocument']}",
                "data": dict(row),
            })

        # Payments (deduplicated by accountingDocument)
        for row in conn.execute("""
            SELECT DISTINCT accountingDocument, clearingAccountingDocument, customer,
                   clearingDate, postingDate,
                   SUM(amountInTransactionCurrency) as totalAmount
            FROM payments
            GROUP BY accountingDocument
        """):
            nodes.append({
                "id": f"PAY_{row['accountingDocument']}",
                "type": "Payment",
                "label": f"PAY {row['accountingDocument']}",
                "data": dict(row),
            })

        # Products
        for row in conn.execute("""
            SELECT p.product, p.productType, p.productOldId, p.productGroup,
                   pd.productDescription
            FROM products p
            LEFT JOIN product_descriptions pd ON p.product = pd.product AND pd.language = 'EN'
        """):
            nodes.append({
                "id": f"PROD_{row['product']}",
                "type": "Product",
                "label": row["productDescription"] or row["productOldId"] or row["product"],
                "data": dict(row),
            })

        # Plants
        for row in conn.execute("SELECT plant, plantName FROM plants"):
            nodes.append({
                "id": f"PLANT_{row['plant']}",
                "type": "Plant",
                "label": row["plantName"] or row["plant"],
                "data": dict(row),
            })

        # --- EDGES ---

        # Customer → Sales Order
        for row in conn.execute("""
            SELECT DISTINCT soldToParty, salesOrder FROM sales_order_headers
            WHERE soldToParty IS NOT NULL AND soldToParty != ''
        """):
            edges.append({
                "source": f"CUST_{row['soldToParty']}",
                "target": f"SO_{row['salesOrder']}",
                "type": "PLACED_ORDER",
            })

        # Sales Order → Delivery (via delivery items)
        for row in conn.execute("""
            SELECT DISTINCT odi.referenceSdDocument as salesOrder, odi.deliveryDocument
            FROM outbound_delivery_items odi
            WHERE odi.referenceSdDocument IS NOT NULL AND odi.referenceSdDocument != ''
        """):
            edges.append({
                "source": f"SO_{row['salesOrder']}",
                "target": f"DEL_{row['deliveryDocument']}",
                "type": "DELIVERED_VIA",
            })

        # Delivery → Billing Document (via billing items)
        for row in conn.execute("""
            SELECT DISTINCT bdi.referenceSdDocument as deliveryDoc, bdi.billingDocument
            FROM billing_document_items bdi
            WHERE bdi.referenceSdDocument IS NOT NULL AND bdi.referenceSdDocument != ''
        """):
            edges.append({
                "source": f"DEL_{row['deliveryDoc']}",
                "target": f"BILL_{row['billingDocument']}",
                "type": "BILLED_VIA",
            })

        # Billing Document → Journal Entry
        for row in conn.execute("""
            SELECT DISTINCT billingDocument, accountingDocument
            FROM billing_document_headers
            WHERE accountingDocument IS NOT NULL AND accountingDocument != ''
        """):
            edges.append({
                "source": f"BILL_{row['billingDocument']}",
                "target": f"JE_{row['accountingDocument']}",
                "type": "POSTED_TO_JOURNAL",
            })

        # Journal Entry → Payment
        for row in conn.execute("""
            SELECT DISTINCT p.accountingDocument as payDoc, p.clearingAccountingDocument as jeDoc
            FROM payments p
            WHERE p.clearingAccountingDocument IS NOT NULL AND p.clearingAccountingDocument != ''
        """):
            edges.append({
                "source": f"JE_{row['jeDoc']}",
                "target": f"PAY_{row['payDoc']}",
                "type": "CLEARED_BY_PAYMENT",
            })

        # Sales Order Item → Product
        for row in conn.execute("""
            SELECT DISTINCT salesOrder, salesOrderItem, material
            FROM sales_order_items
            WHERE material IS NOT NULL AND material != ''
        """):
            edges.append({
                "source": f"SO_{row['salesOrder']}",
                "target": f"PROD_{row['material']}",
                "type": "CONTAINS_PRODUCT",
            })

        # Delivery → Plant
        for row in conn.execute("""
            SELECT DISTINCT deliveryDocument, plant
            FROM outbound_delivery_items
            WHERE plant IS NOT NULL AND plant != ''
        """):
            edges.append({
                "source": f"DEL_{row['deliveryDocument']}",
                "target": f"PLANT_{row['plant']}",
                "type": "SHIPPED_FROM",
            })

    finally:
        conn.close()

    return {"nodes": nodes, "edges": edges}


# ==============================================================================
# CLI ENTRY POINT
# ==============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build O2C SQLite database from JSONL data")
    parser.add_argument("--data-dir", default="./sap-o2c-data", help="Path to sap-o2c-data directory")
    parser.add_argument("--db-path", default="./data/o2c.db", help="Output SQLite database path")
    args = parser.parse_args()

    print(f"Building database from: {args.data_dir}")
    print(f"Output: {args.db_path}\n")

    stats = build_database(args.data_dir, args.db_path)

    print(f"\nDone. Total rows: {sum(stats.values())}")
    print(f"Database size: {os.path.getsize(args.db_path) / 1024:.1f} KB")

    # Quick graph export test
    print("\nExporting graph data...")
    graph = export_graph_data(args.db_path)
    print(f"  Nodes: {len(graph['nodes'])}")
    print(f"  Edges: {len(graph['edges'])}")
    node_types = {}
    for n in graph["nodes"]:
        node_types[n["type"]] = node_types.get(n["type"], 0) + 1
    for t, c in sorted(node_types.items()):
        print(f"    {t}: {c}")
    edge_types = {}
    for e in graph["edges"]:
        edge_types[e["type"]] = edge_types.get(e["type"], 0) + 1
    for t, c in sorted(edge_types.items()):
        print(f"    {t}: {c}")
