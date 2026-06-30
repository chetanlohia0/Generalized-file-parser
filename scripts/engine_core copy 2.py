import pdfplumber
import os
import numpy as np
import json
import re

class GeneralizedDDParser:
    def __init__(self, pdf_path):
        self.pdf_path = pdf_path
        self.doc_id = os.path.splitext(os.path.basename(pdf_path))[0]
        
        # Calibration Metrics (The Physics Layer)
        self.metrics = {
            "avg_line_height": 10.0,
            "standard_gap": 5.0,
            "calibration_successful": False
        }
        
        # Data Storage
        self.raw_tables = []
        self.text_blocks = []
        self.final_tables = [] 

    # =========================================================================
    # PHASE 1: INGESTION & DYNAMIC CALIBRATION
    # =========================================================================
    def calibrate_document_geometry(self):
        """Analyzes early pages to dynamically extract line heights and text flow gaps."""
        line_heights = []
        line_gaps = []
        
        with pdfplumber.open(self.pdf_path) as pdf:
            pages_to_calibrate = pdf.pages[:2]
            for page in pages_to_calibrate:
                tables = page.find_tables()
                table_bboxes = [t.bbox for t in tables]
                
                words = page.extract_words()
                if not words: continue
                
                lines_dict = {}
                for w in words:
                    inside_table = False
                    for bbox in table_bboxes:
                        if w["top"] >= (bbox[1] - 2) and w["bottom"] <= (bbox[3] + 2):
                            inside_table = True
                            break
                    if inside_table: continue
                
                    approx_top = round(w["top"])
                    found_match = False
                    for distinct_top in lines_dict.keys():
                        if abs(approx_top - distinct_top) <= 3:
                            lines_dict[distinct_top].append(w)
                            found_match = True
                            break
                    if not found_match:
                        lines_dict[approx_top] = [w]
                
                sorted_tops = sorted(lines_dict.keys())
                for i, top in enumerate(sorted_tops):
                    line_words = lines_dict[top]
                    max_bottom = max(w["bottom"] for w in line_words)
                    min_top = min(w["top"] for w in line_words)
                    line_heights.append(max_bottom - min_top)
                    
                    if i > 0:
                        prev_top = sorted_tops[i-1]
                        prev_bottom = max(w["bottom"] for w in lines_dict[prev_top])
                        gap = min_top - prev_bottom
                        if 0 < gap < 100:
                            line_gaps.append(gap)
                            
        if line_heights and line_gaps:
            self.metrics["avg_line_height"] = float(np.median(line_heights))
            self.metrics["standard_gap"] = float(np.median(line_gaps))
            self.metrics["calibration_successful"] = True
            
        print(f"🔬 Calibrated Geometry [{self.doc_id}]: Height={self.metrics['avg_line_height']:.2f}px, Gap={self.metrics['standard_gap']:.2f}px")
        return self.metrics

    # =========================================================================
    # PHASE 2: STRUCTURAL RECONSTRUCTION
    # =========================================================================
    def _is_inside_table(self, text_top, text_bottom, page_tables):
        for t in page_tables:
            if text_top >= (t["top_y"] - 2) and text_bottom <= (t["bottom_y"] + 2):
                return True
        return False

    def _consolidate_rows(self, raw_rows):
        cleaned_rows = []
        for raw_row in raw_rows:
            row = [str(cell).strip().replace('\n', ' ') if cell else "" for cell in raw_row]
            if not any(row): continue
                
            if not row[0] and cleaned_rows:
                for i in range(len(row)):
                    if row[i]:
                        cleaned_rows[-1][i] = f"{cleaned_rows[-1][i]} {row[i]}".strip()
            else:
                cleaned_rows.append(row)
        return cleaned_rows

    def extract_page_elements(self):
        """Extracts text streams and table coordinates across all pages."""
        self.raw_tables = []
        self.text_blocks = []
        
        with pdfplumber.open(self.pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                tables = page.find_tables()
                page_tables_meta = []
                
                for t_idx, table in enumerate(tables):
                    bbox = table.bbox
                    data = table.extract()
                    consolidated_data = self._consolidate_rows(data)
                    
                    table_meta = {
                        "table_id": f"p{page_num}_t{t_idx}",
                        "pages": [page_num],
                        "last_page": page_num,
                        "bbox": bbox,
                        "top_y": bbox[1],
                        "bottom_y": bbox[3],
                        "rows": consolidated_data,
                        "intro_text": None,
                        "footer_notes": None
                    }
                    self.raw_tables.append(table_meta)
                    page_tables_meta.append(table_meta)
                
                words = page.extract_words()
                lines_dict = {}
                for w in words:
                    approx_top = round(w["top"])
                    found_match = False
                    for distinct_top in lines_dict.keys():
                        if abs(approx_top - distinct_top) <= 3:
                            lines_dict[distinct_top].append(w)
                            found_match = True
                            break
                    if not found_match:
                        lines_dict[approx_top] = [w]
                        
                for top in sorted(lines_dict.keys()):
                    line_words = lines_dict[top]
                    text = " ".join([w['text'] for w in line_words]).strip()
                    min_top = min(w["top"] for w in line_words)
                    max_bottom = max(w["bottom"] for w in line_words)
                    
                    if self._is_inside_table(min_top, max_bottom, page_tables_meta):
                        continue
                        
                    self.text_blocks.append({
                        "page": page_num,
                        "text": text,
                        "top_y": min_top,
                        "bottom_y": max_bottom,
                        "rel_top_y": min_top / page.height, # Orientation-flipped percentage geometry
                        "associated_table": None,
                        "position": "standalone"
                    })

    # =========================================================================
    # PHASE 1.5: GLOBAL SPATIAL DE-NOISING (BOILERPLATE REMOVAL)
    # =========================================================================
    def remove_boilerplate_text(self):
        """
        Identifies and purges repeating headers, footers, watermarks, and templates.
        Uses digit masking to catch variable counters (like Page 1 vs Page 2)
        and relative Y matching to handle portrait/landscape transitions.
        """
        if not self.text_blocks: return
        
        total_pages = max(b["page"] for b in self.text_blocks)
        # Scale filter window threshold to fit short and long documents smoothly
        frequency_threshold = max(2, int(total_pages * 0.25))
        
        signature_counts = {}
        for b in self.text_blocks:
            # Mask out digits to uncover underlying structural signatures
            masked_text = re.sub(r'\d', '#', b["text"].lower().strip())
            if not masked_text: continue
            
            # Key uses text signature combined with a rounded relative vertical placement band
            spatial_key = (masked_text, round(b["rel_top_y"], 2))
            
            if spatial_key not in signature_counts:
                signature_counts[spatial_key] = set()
            signature_counts[spatial_key].add(b["page"])
            
        # Extract keys that exist across a high concentration of the page layout pools
        boilerplate_keys = {k for k, pages in signature_counts.items() if len(pages) >= frequency_threshold}
        
        cleaned_blocks = []
        removed_count = 0
        for b in self.text_blocks:
            masked_text = re.sub(r'\d', '#', b["text"].lower().strip())
            spatial_key = (masked_text, round(b["rel_top_y"], 2))
            
            if spatial_key in boilerplate_keys:
                removed_count += 1
                continue # Wipe element out of processing stream
            cleaned_blocks.append(b)
            
        self.text_blocks = cleaned_blocks
        print(f"🧹 [DE-NOISE] Purged {removed_count} recurring header/footer layout components from the text stream.")

    # =========================================================================
    # PHASE 2.3: MONOLITHIC MULTI-PAGE STITCHING ENGINE
    # =========================================================================
    def stitch_multi_page_tables(self):
        """
        Stitches schema elements using strict verification gates.
        Requires matrix congruence, structural header continuity, 
        and verifies there is zero intervening narrative context.
        """
        self.final_tables = []
        header_limit = self.metrics["avg_line_height"] * 8
        
        for t in self.raw_tables:
            if not self.final_tables:
                self.final_tables.append(t)
                continue
                
            prev_t = self.final_tables[-1]
            
            # --- GATE 1: Matrix Column Count Alignment ---
            if prev_t["rows"] and t["rows"] and len(t["rows"][0]) == len(prev_t["rows"][0]):
                
                # --- GATE 2: Structural Header Match OR Serial Number Progression ---
                headers_match = (t["rows"][0] == prev_t["rows"][0])
                serial_continues = False
                
                if not headers_match:
                    # Parse final row digit identifier vs incoming row digit identifier
                    prev_sn_match = re.findall(r'\d+', str(prev_t["rows"][-1][0]))
                    curr_sn_match = re.findall(r'\d+', str(t["rows"][0][0]))
                    if prev_sn_match and curr_sn_match:
                        try:
                            if int(curr_sn_match[0]) == int(prev_sn_match[0]) + 1:
                                serial_continues = True
                        except ValueError:
                            pass
                
                # Proceed only if structural continuation patterns exist cleanly
                if headers_match or serial_continues:
                    
                    # --- GATE 3: Intervening Context Block Scan ---
                    has_intervening_text = False
                    for tb in self.text_blocks:
                        if prev_t["last_page"] == t["pages"][0] == tb["page"]:
                            if prev_t["bottom_y"] < tb["top_y"] and tb["bottom_y"] < t["top_y"]:
                                has_intervening_text = True
                                break
                        elif t["pages"][0] == prev_t["last_page"] + 1:
                            if tb["page"] == t["pages"][0]:
                                if t["top_y"] > header_limit and tb["bottom_y"] < t["top_y"]:
                                    has_intervening_text = True
                                    break
                                    
                    if not has_intervening_text:
                        # Clear to merge! If headers repeat, strip the top row.
                        start_row_idx = 1 if headers_match else 0
                        prev_t["rows"].extend(t["rows"][start_row_idx:])
                        
                        if t["pages"][0] not in prev_t["pages"]:
                            prev_t["pages"].append(t["pages"][0])
                        prev_t["last_page"] = t["pages"][0]
                        prev_t["bottom_y"] = t["bottom_y"]
                        continue
                        
            self.final_tables.append(t)
        print(f"🔗 [STITCH] Combined cross-page schemas down into {len(self.final_tables)} integrated table entities.")

    def attach_spatial_context(self):
        proximity_bound = self.metrics["avg_line_height"] * 2.5
        for tb in self.text_blocks:
            page_num = tb["page"]
            for table in [t for t in self.final_tables if t["pages"][0] == page_num]:
                gap_above = table["top_y"] - tb["bottom_y"]
                if 0 < gap_above <= proximity_bound:
                    table["intro_text"] = tb["text"]
                    tb["associated_table"] = table["table_id"]
                    tb["position"] = "pre_table"
                    break
            if tb["position"] != "standalone": continue
            for table in [t for t in self.final_tables if t["last_page"] == page_num]:
                gap_below = tb["top_y"] - table["bottom_y"]
                if 0 < gap_below <= proximity_bound:
                    if tb["text"].startswith(("*", "Note", "Values", "See", "Valid")):
                        if table["footer_notes"]:
                            table["footer_notes"] += " " + tb["text"]
                        else:
                            table["footer_notes"] = tb["text"]
                        tb["associated_table"] = table["table_id"]
                        tb["position"] = "post_table"
                        break

    # =========================================================================
    # PHASE 4: OUTPUT EXPORT ENGINE
    # =========================================================================
    def export_results(self, output_base_dir="outputs"):
        doc_dir = os.path.join(output_base_dir, self.doc_id)
        os.makedirs(doc_dir, exist_ok=True)
        
        main_schemas = []
        lookup_references = []
        for t in self.final_tables:
            if len(t["rows"][0]) > 3:
                main_schemas.append(t)
            else:
                lookup_references.append(t)
                
        format_a = {
            "document_id": self.doc_id,
            "main_tables": main_schemas,
            "lookup_tables": lookup_references,
            "standalone_text": [b for b in self.text_blocks if b["position"] == "standalone"],
            "relationships": []
        }
        with open(os.path.join(doc_dir, "unified_format_A.json"), "w", encoding="utf-8") as f:
            json.dump(format_a, f, indent=2, ensure_ascii=False)
        with open(os.path.join(doc_dir, "main_tables.json"), "w", encoding="utf-8") as f:
            json.dump({"document": self.doc_id, "tables": main_schemas}, f, indent=2, ensure_ascii=False)
        with open(os.path.join(doc_dir, "lookup_tables.json"), "w", encoding="utf-8") as f:
            json.dump({"document": self.doc_id, "lookups": lookup_references}, f, indent=2, ensure_ascii=False)
        with open(os.path.join(doc_dir, "text_context.json"), "w", encoding="utf-8") as f:
            json.dump({"document": self.doc_id, "blocks": self.text_blocks}, f, indent=2, ensure_ascii=False)

# =========================================================================
# SYSTEM ORCHESTRATOR
# =========================================================================
if __name__ == "__main__":
    PDF_DIRECTORY = "pdf"
    if os.path.exists(PDF_DIRECTORY):
        pdf_files = [f for f in os.listdir(PDF_DIRECTORY) if f.lower().endswith(".pdf")]
        if pdf_files:
            print(f"📂 Found {len(pdf_files)} PDF file(s) for verification pipeline processing.\n")
            for pdf_file in pdf_files:
                full_path = os.path.join(PDF_DIRECTORY, pdf_file)
                parser = GeneralizedDDParser(full_path)
                
                # Run the newly structured decoupled pipeline
                parser.calibrate_document_geometry()
                parser.extract_page_elements()
                parser.remove_boilerplate_text() # Phase 1.5
                parser.stitch_multi_page_tables() # Reinforced Multi-Gate 2.3
                parser.attach_spatial_context()
                parser.export_results()
                print(f"🏁 Processing finished for: {parser.doc_id}\n" + "-"*60)