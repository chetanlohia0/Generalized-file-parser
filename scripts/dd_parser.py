import pdfplumber
import json
import os
import re

# ==========================================
# CONFIGURATION
# ==========================================
PDF_DIR = "pdf"
OUTPUT_DIR = "outputs"
FILE_NAME = "2.pdf" # Change this to test other files
PDF_PATH = os.path.join(PDF_DIR, FILE_NAME)

# Create output directories if they don't exist
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ==========================================
# STAGE 1 & 2: RAW EXTRACTION & STITCHING
# ==========================================
def extract_and_stitch_tables(pdf_path):
    """
    Extracts tables and text blocks with their exact spatial bounding boxes.
    (Stitching logic for multi-page tables can be expanded here).
    """
    raw_data = {"tables": [], "text_blocks": []}
    
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            
            # 1. Extract Tables with Bounding Boxes
            tables = page.find_tables()
            for t_idx, table in enumerate(tables):
                bbox = table.bbox # (x0, y0, x1, y1)
                data = table.extract()
                
                # Basic cleanup of table data
                cleaned_data = [[cell.replace('\n', ' ') if cell else "" for cell in row] for row in data]
                
                raw_data["tables"].append({
                    "table_id": f"p{page_num}_t{t_idx}",
                    "page": page_num,
                    "bbox": bbox, # Crucial for layout fidelity
                    "top_y": bbox[1],
                    "bottom_y": bbox[3],
                    "rows": cleaned_data,
                    "intro_text": None,
                    "footer_notes": None
                })
                
            # 2. Extract Text Blocks with Bounding Boxes
            # Using extract_words to reconstruct lines and get their coordinates
            words = page.extract_words()
            lines = []
            current_line = []
            current_y = None
            
            for word in words:
                if current_y is None or abs(word['top'] - current_y) < 5:
                    current_line.append(word)
                    current_y = word['top']
                else:
                    lines.append(current_line)
                    current_line = [word]
                    current_y = word['top']
            if current_line:
                lines.append(current_line)

            for line in lines:
                text = " ".join([w['text'] for w in line])
                top_y = min([w['top'] for w in line])
                bottom_y = max([w['bottom'] for w in line])
                
                raw_data["text_blocks"].append({
                    "page": page_num,
                    "text": text,
                    "top_y": top_y,
                    "bottom_y": bottom_y,
                    "associated_table": None,
                    "position": "standalone"
                })
                
    return raw_data

# ==========================================
# STAGE 3: SPATIAL CONTEXT ATTACHER
# ==========================================
def attach_spatial_context(raw_data):
    """
    Links text blocks to tables based on precise Y-coordinate positioning.
    Zone 1: Pre-table (intro)
    Zone 2: Post-table (footer)
    Zone 3: Standalone (unrelated)
    """
    for text_block in raw_data["text_blocks"]:
        page_num = text_block["page"]
        t_top = text_block["top_y"]
        t_bottom = text_block["bottom_y"]
        
        # Find tables on the same page
        page_tables = [t for t in raw_data["tables"] if t["page"] == page_num]
        
        for table in page_tables:
            # Zone 1 Check (Intro Text): Text ends just above the table
            gap_above = table["top_y"] - t_bottom
            if 0 < gap_above < 40: # within 40 pixels above
                table["intro_text"] = text_block["text"]
                text_block["associated_table"] = table["table_id"]
                text_block["position"] = "pre_table"
                break
                
            # Zone 2 Check (Footer Note): Text starts just below the table
            gap_below = t_top - table["bottom_y"]
            if 0 < gap_below < 40: # within 40 pixels below
                # Additional relevance check (e.g., starts with asterisk or 'Note')
                if text_block["text"].startswith(("*", "Note", "Values")):
                    table["footer_notes"] = text_block["text"]
                    text_block["associated_table"] = table["table_id"]
                    text_block["position"] = "post_table"
                    break

    return raw_data

# ==========================================
# STAGE 4 & 5: VALUE HINTS & RELATIONSHIPS (Stub)
# ==========================================
def analyze_relationships(processed_data):
    """
    Identifies if a table is a main schema or a lookup table.
    Extracts value hints using basic regex.
    """
    main_tables = []
    lookup_tables = []
    relationships = []
    
    for table in processed_data["tables"]:
        rows = table["rows"]
        if not rows: continue
        
        # Very basic heuristic: if it has more than 3 columns, it's a main table.
        # Otherwise, it's likely a lookup table.
        if len(rows[0]) > 3:
            main_tables.append(table)
        else:
            lookup_tables.append(table)
            
    # Example Relationship Stub (We will expand this later)
    relationships.append({
        "from_table": "Medical Claims",
        "from_column": "CLAIM_TYPE",
        "to_table": "Claim Type Codes",
        "type": "lookup",
        "confidence": 0.85
    })
            
    return main_tables, lookup_tables, relationships

# ==========================================
# STAGE 6: EXPORT
# ==========================================
def export_json(main_tables, lookup_tables, text_blocks, relationships, doc_name):
    """
    Exports the data into Format A (Unified) and Format B (Split).
    """
    doc_id = doc_name.replace(".pdf", "")
    out_dir = os.path.join(OUTPUT_DIR, doc_id)
    os.makedirs(out_dir, exist_ok=True)
    
    # --- FORMAT A: Unified ---
    format_a = {
        "document_id": doc_id,
        "main_tables": main_tables,
        "lookup_tables": lookup_tables,
        "text_blocks": text_blocks,
        "relationships": relationships
    }
    
    with open(os.path.join(out_dir, "unified_format_A.json"), "w") as f:
        json.dump(format_a, f, indent=2)
        
    # --- FORMAT B: Split ---
    with open(os.path.join(out_dir, "main_tables.json"), "w") as f:
        json.dump({"document": doc_id, "tables": main_tables}, f, indent=2)
        
    with open(os.path.join(out_dir, "lookup_tables.json"), "w") as f:
        json.dump({"document": doc_id, "lookups": lookup_tables}, f, indent=2)
        
    with open(os.path.join(out_dir, "text_context.json"), "w") as f:
        json.dump({"document": doc_id, "blocks": text_blocks}, f, indent=2)
        
    print(f"✅ Successfully extracted {doc_name}")
    print(f"📁 Output saved to: {out_dir}")

# ==========================================
# MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    print(f"🚀 Starting extraction for {FILE_NAME}...")
    
    if not os.path.exists(PDF_PATH):
        print(f"❌ Error: Cannot find {PDF_PATH}. Make sure the file exists.")
    else:
        # Run Pipeline
        raw_data = extract_and_stitch_tables(PDF_PATH)
        processed_data = attach_spatial_context(raw_data)
        m_tables, l_tables, rels = analyze_relationships(processed_data)
        export_json(m_tables, l_tables, processed_data["text_blocks"], rels, FILE_NAME)