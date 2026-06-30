import pdfplumber
import json
import os
import re

# ==========================================
# CONFIGURATION
# ==========================================
PDF_DIR = "pdf"
OUTPUT_DIR = "outputs"
FILE_NAME = "APAC 2024 claims file layout Appendices A-G.pdf" # Adjust to test other files
PDF_PATH = os.path.join(PDF_DIR, FILE_NAME)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ==========================================
# HELPER FUNCTIONS
# ==========================================
def is_inside_table(text_top, text_bottom, tables_on_page):
    """
    GAP 2 FIX: Checks if a text line's coordinates fall inside any table's bounding box.
    Prevents table data from bleeding into the standalone text blocks.
    """
    for t in tables_on_page:
        # Adding a 2-pixel buffer to account for minor parsing overlaps
        if text_top >= (t["top_y"] - 2) and text_bottom <= (t["bottom_y"] + 2):
            return True
    return False

def consolidate_rows(raw_rows):
    """
    GAP 1 FIX: Heuristic to fix multiline row fragmentation.
    If a row has empty initial columns (like S.N. or Column Name), 
    it is likely a wrapped text continuation of the previous row.
    """
    cleaned_rows = []
    
    for raw_row in raw_rows:
        # Convert all None types to empty strings and strip whitespace
        row = [str(cell).strip().replace('\n', ' ') if cell else "" for cell in raw_row]
        
        # Skip completely empty rows
        if not any(row):
            continue
            
        # If the first column (e.g., S.N. or Name) is empty, but we have a previous row,
        # append the text of this row to the corresponding cells of the previous row.
        if not row[0] and cleaned_rows:
            for i in range(len(row)):
                if row[i]:
                    # Add a space before appending the continued text
                    cleaned_rows[-1][i] += " " + row[i]
                    cleaned_rows[-1][i] = cleaned_rows[-1][i].strip()
        else:
            # It's a brand new row, add it to the list
            cleaned_rows.append(row)
            
    return cleaned_rows

# ==========================================
# STAGE 1 & 2: RAW EXTRACTION & STITCHING
# ==========================================
def extract_and_stitch_tables(pdf_path):
    raw_tables = []
    text_blocks = []
    
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            
            # --- 1. EXTRACT TABLES ---
            tables = page.find_tables()
            page_tables_meta = []
            
            for t_idx, table in enumerate(tables):
                bbox = table.bbox 
                data = table.extract()
                
                # Apply Gap 1 Fix: Consolidate fragmented rows
                consolidated_data = consolidate_rows(data)
                
                table_meta = {
                    "table_id": f"p{page_num}_t{t_idx}",
                    "pages": [page_num],
                    "last_page": page_num, # Used to know where to attach footers later
                    "bbox": bbox,
                    "top_y": bbox[1],
                    "bottom_y": bbox[3],
                    "rows": consolidated_data,
                    "intro_text": None,
                    "footer_notes": None
                }
                raw_tables.append(table_meta)
                page_tables_meta.append(table_meta)
                
            # --- 2. EXTRACT TEXT (WITH EXCLUSION) ---
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
                text = " ".join([w['text'] for w in line]).strip()
                top_y = min([w['top'] for w in line])
                bottom_y = max([w['bottom'] for w in line])
                
                # Apply Gap 2 Fix: Skip text if it's inside a table
                if is_inside_table(top_y, bottom_y, page_tables_meta):
                    continue
                    
                text_blocks.append({
                    "page": page_num,
                    "text": text,
                    "top_y": top_y,
                    "bottom_y": bottom_y,
                    "associated_table": None,
                    "position": "standalone"
                })

  # --- 3. GAP 3 FIX: STITCH MULTI-PAGE TABLES (WITH INTERVENING TEXT CHECK) ---
    stitched_tables = []
    for t in raw_tables:
        if not stitched_tables:
            stitched_tables.append(t)
            continue
            
        prev_t = stitched_tables[-1]
        
        # Check if column counts match
        if prev_t["rows"] and t["rows"] and len(t["rows"][0]) == len(prev_t["rows"][0]):
            # Check if headers match explicitly
            if t["rows"][0] == prev_t["rows"][0]:
                
                # --- NEW LOGIC: Check for intervening text ---
                has_intervening_text = False
                
                for tb in text_blocks:
                    # Condition A: Tables are on the SAME page
                    if prev_t["last_page"] == t["pages"][0] == tb["page"]:
                        # Is the text physically between Table A's bottom and Table B's top?
                        if prev_t["bottom_y"] < tb["top_y"] and tb["bottom_y"] < t["top_y"]:
                            has_intervening_text = True
                            break
                            
                    # Condition B: Tables are on ADJACENT pages
                    elif t["pages"][0] == prev_t["last_page"] + 1:
                        if tb["page"] == t["pages"][0]:
                            # If Table B doesn't start at the top of the new page (e.g., > 100px down)
                            # AND there is text above it, it's a new section, not a continuation.
                            if t["top_y"] > 100 and tb["bottom_y"] < t["top_y"]:
                                has_intervening_text = True
                                break

                # If no text separates them, it's safe to stitch!
                if not has_intervening_text:
                    print(f"   🔗 Stitching continuation table on page {t['pages'][0]}.")
                    # Merge rows (skipping the duplicate header)
                    prev_t["rows"].extend(t["rows"][1:])
                    
                    # Safely append page number without duplicates
                    if t["pages"][0] not in prev_t["pages"]:
                        prev_t["pages"].append(t["pages"][0])
                        
                    prev_t["last_page"] = t["pages"][0]
                    prev_t["bottom_y"] = t["bottom_y"] # Update bottom edge
                    continue
                else:
                    print(f"   ✂️  Skipping stitch on page {t['pages'][0]} (intervening text detected).")
                
        # If we reach here, either headers didn't match, or text separated them
        stitched_tables.append(t)
                
    return {"tables": stitched_tables, "text_blocks": text_blocks}
# ==========================================
# STAGE 3: SPATIAL CONTEXT ATTACHER
# ==========================================
def attach_spatial_context(raw_data):
    for text_block in raw_data["text_blocks"]:
        page_num = text_block["page"]
        t_top = text_block["top_y"]
        t_bottom = text_block["bottom_y"]
        
        # Zone 1 Check (Intro Text): Only look at tables that START on this page
        for table in [t for t in raw_data["tables"] if t["pages"][0] == page_num]:
            gap_above = table["top_y"] - t_bottom
            if 0 < gap_above < 40:
                table["intro_text"] = text_block["text"]
                text_block["associated_table"] = table["table_id"]
                text_block["position"] = "pre_table"
                break
                
        if text_block["position"] != "standalone":
            continue # Already attached as intro, move to next block
            
        # Zone 2 Check (Footer Note): Only look at tables that END on this page
        for table in [t for t in raw_data["tables"] if t["last_page"] == page_num]:
            gap_below = t_top - table["bottom_y"]
            if 0 < gap_below < 40:
                if text_block["text"].startswith(("*", "Note", "Values", "See")):
                    # If multiple notes, append them
                    if table["footer_notes"]:
                        table["footer_notes"] += " " + text_block["text"]
                    else:
                        table["footer_notes"] = text_block["text"]
                        
                    text_block["associated_table"] = table["table_id"]
                    text_block["position"] = "post_table"
                    break

    return raw_data

# ==========================================
# STAGE 4 & 5: VALUE HINTS & RELATIONSHIPS
# ==========================================
def analyze_relationships(processed_data):
    main_tables = []
    lookup_tables = []
    relationships = []
    
    for table in processed_data["tables"]:
        rows = table["rows"]
        if not rows: continue
        
        if len(rows[0]) > 3:
            main_tables.append(table)
        else:
            lookup_tables.append(table)
            
    return main_tables, lookup_tables, relationships

# ==========================================
# STAGE 6: EXPORT
# ==========================================
def export_json(main_tables, lookup_tables, text_blocks, relationships, doc_name):
    doc_id = doc_name.replace(".pdf", "")
    out_dir = os.path.join(OUTPUT_DIR, doc_id)
    os.makedirs(out_dir, exist_ok=True)
    
    format_a = {
        "document_id": doc_id,
        "main_tables": main_tables,
        "lookup_tables": lookup_tables,
        "text_blocks": text_blocks,
        "relationships": relationships
    }
    
    with open(os.path.join(out_dir, "unified_format_A.json"), "w") as f:
        json.dump(format_a, f, indent=2)
        
    with open(os.path.join(out_dir, "main_tables.json"), "w") as f:
        json.dump({"document": doc_id, "tables": main_tables}, f, indent=2)
        
    with open(os.path.join(out_dir, "lookup_tables.json"), "w") as f:
        json.dump({"document": doc_id, "lookups": lookup_tables}, f, indent=2)
        
    with open(os.path.join(out_dir, "text_context.json"), "w") as f:
        json.dump({"document": doc_id, "blocks": text_blocks}, f, indent=2)
        
    print(f"✅ Successfully extracted {doc_name}")

# ==========================================
# MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    print(f"🚀 Starting extraction for {FILE_NAME}...\n")
    
    if not os.path.exists(PDF_PATH):
        print(f"❌ Error: Cannot find {PDF_PATH}. Make sure the file exists.")
    else:
        raw_data = extract_and_stitch_tables(PDF_PATH)
        processed_data = attach_spatial_context(raw_data)
        m_tables, l_tables, rels = analyze_relationships(processed_data)
        export_json(m_tables, l_tables, processed_data["text_blocks"], rels, FILE_NAME)