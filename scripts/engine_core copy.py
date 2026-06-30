import pdfplumber
import os
import numpy as np

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
        self.final_tables = [] # Holds finalized stitched tables

    # =========================================================================
    # PHASE 1: INGESTION & DYNAMIC CALIBRATION
    # =========================================================================
    def calibrate_document_geometry(self):
        """
        Analyzes the first 2 pages to dynamically calculate line heights and gaps.
        Excludes table regions to ensure metrics only represent narrative paragraph flow.
        """
        print(f"🔬 Calibrating document geometry for: {self.doc_id}...")
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
            
        print(f"📊 Calibration Parameters Computed: Height={self.metrics['avg_line_height']:.2f}px, Gap={self.metrics['standard_gap']:.2f}px")
        return self.metrics

    # =========================================================================
    # PHASE 2: STRUCTURAL RECONSTRUCTION
    # =========================================================================
    def _is_inside_table(self, text_top, text_bottom, page_tables):
        """Step 2.2: Bounding Box Exclusion Gate using a 2px geometric buffer."""
        for t in page_tables:
            if text_top >= (t["top_y"] - 2) and text_bottom <= (t["bottom_y"] + 2):
                return True
        return False

    def _consolidate_rows(self, raw_rows):
        """Step 2.1: Semantic Row Consolidation logic using standard column evaluation."""
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
        """Orchestrates layer isolation across all pages of the document."""
        print(f"🏗️  Running Phase 2 Structural Extraction for: {self.doc_id}...")
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
                        "associated_table": None,
                        "position": "standalone"
                    })
                    
        print(f"   -> Isolated {len(self.raw_tables)} raw tables and {len(self.text_blocks)} raw text blocks.")

    def stitch_multi_page_tables(self):
        """
        Step 2.3: Strict-Gate Multi-Page Table Stitching Engine.
        Uses calibrated line bounds to check for intervening text across pages.
        """
        print(f"🔗 Executing multi-page stitching engine for: {self.doc_id}...")
        self.final_tables = []
        
        # Calculate a generalized threshold for what constitutes an active text header space
        # (e.g., if text drops lower than 8 lines worth of height, it's a real paragraph block, not a running header)
        header_limit = self.metrics["avg_line_height"] * 8
        
        for t in self.raw_tables:
            if not self.final_tables:
                self.final_tables.append(t)
                continue
                
            prev_t = self.final_tables[-1]
            
            # GATE A & B: Column matrix structural verification
            if prev_t["rows"] and t["rows"] and len(t["rows"][0]) == len(prev_t["rows"][0]):
                if t["rows"][0] == prev_t["rows"][0]:
                    
                    # GATE C: Generalized Intervening Text Check
                    has_intervening_text = False
                    
                    for tb in self.text_blocks:
                        # Case 1: Multiple discrete tables are printed on the same page
                        if prev_t["last_page"] == t["pages"][0] == tb["page"]:
                            if prev_t["bottom_y"] < tb["top_y"] and tb["bottom_y"] < t["top_y"]:
                                has_intervening_text = True
                                break
                                
                        # Case 2: Table splits across adjacent pages
                        elif t["pages"][0] == prev_t["last_page"] + 1:
                            if tb["page"] == t["pages"][0]:
                                # Check if text sits above the table on the new page, 
                                # dropping lower than the standard running page header zone
                                if t["top_y"] > header_limit and tb["bottom_y"] < t["top_y"]:
                                    has_intervening_text = True
                                    break
                                    
                    if not has_intervening_text:
                        print(f"   🔗 [STITCH] Appending page {t['pages'][0]} table onto tracking table {prev_t['table_id']}.")
                        prev_t["rows"].extend(t["rows"][1:]) # Drop the duplicate header row
                        if t["pages"][0] not in prev_t["pages"]:
                            prev_t["pages"].append(t["pages"][0])
                        prev_t["last_page"] = t["pages"][0]
                        prev_t["bottom_y"] = t["bottom_y"]
                        continue
                    else:
                        print(f"   ✂️  [SEPARATE] Found dividing text on page {t['pages'][0]}. Keeping separate.")
                        
            self.final_tables.append(t)
            
        print(f"   -> Reconstructed raw elements down into {len(self.final_tables)} continuous unified table entities.\n")

# =========================================================================
# GENERALIZED MULTI-FILE EXECUTION TESTER
# =========================================================================
if __name__ == "__main__":
    PDF_DIRECTORY = "pdf"
    
    if os.path.exists(PDF_DIRECTORY):
        pdf_files = [f for f in os.listdir(PDF_DIRECTORY) if f.lower().endswith(".pdf")]
        if pdf_files:
            print(f"📂 Found {len(pdf_files)} PDF file(s) for processing.\n")
            for pdf_file in pdf_files:
                full_path = os.path.join(PDF_DIRECTORY, pdf_file)
                parser = GeneralizedDDParser(full_path)
                
                # Execute Pipeline Phases sequentially
                parser.calibrate_document_geometry()
                parser.extract_page_elements()
                parser.stitch_multi_page_tables()
                print("-" * 60)