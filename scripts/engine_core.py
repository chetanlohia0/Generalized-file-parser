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
        
        # Pipelines data arrays
        self.raw_tables = []
        self.raw_lines = []
        self.paragraphs = []
        self.final_tables = []

    # =========================================================================
    # STAGE 1: DYNAMIC GEOMETRY CALIBRATION
    # =========================================================================
    def calibrate_document_geometry(self):
        """Calculates line height and gap baselines using non-table text zones."""
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
            
        print(f"🔬 Calibration [{self.doc_id}]: Height={self.metrics['avg_line_height']:.2f}px, Gap={self.metrics['standard_gap']:.2f}px")

    # =========================================================================
    # STAGE 2: RAW STREAM SEPARATION
    # =========================================================================
    def extract_raw_components(self):
        """Extracts text streams and table elements into independent un-merged arrays."""
        self.raw_tables = []
        self.raw_lines = []
        
        with pdfplumber.open(self.pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                # Extract Tables
                tables = page.find_tables()
                page_tables_meta = []
                for t_idx, table in enumerate(tables):
                    bbox = table.bbox
                    data = table.extract()
                    
                    # Clean up interior row text wrap carriage returns
                    cleaned_data = [[cell.replace('\n', ' ').strip() if cell else "" for cell in row] for row in data]
                    
                    table_meta = {
                        "table_id": f"p{page_num}_t{t_idx}",
                        "page": page_num,
                        "pages": [page_num],
                        "last_page": page_num,
                        "bbox": bbox,
                        "top_y": bbox[1],
                        "bottom_y": bbox[3],
                        "rows": cleaned_data
                    }
                    self.raw_tables.append(table_meta)
                    page_tables_meta.append(table_meta)
                
                # Extract Text Lines
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
                    
                    # Coordinate exclusion gate: Skip line if it's inside a table matrix
                    inside_table = False
                    for t in page_tables_meta:
                        if min_top >= (t["top_y"] - 2) and max_bottom <= (t["bottom_y"] + 2):
                            inside_table = True
                            break
                    if inside_table: continue
                    
                    self.raw_lines.append({
                        "page": page_num,
                        "text": text,
                        "top_y": min_top,
                        "bottom_y": max_bottom
                    })

    # =========================================================================
    # STAGE 3: GLOBAL LOGICAL DE-NOISING
    # =========================================================================
    def remove_boilerplate_noise(self):
        """Decouples layout from pixels, erasing recurring string patterns via digit tokens."""
        if not self.raw_lines: return
        
        total_pages = max(l["page"] for l in self.raw_lines)
        # Calculate dynamic recurrence limit based on total document volume
        occurrence_limit = max(2, int(total_pages * 0.25))
        
        signature_counts = {}
        for l in self.raw_lines:
            # Tokenize numbers to generalize variant labels (e.g. Page 1 vs Page 2)
            tokenized = re.sub(r'\d+', '#', l["text"].lower().strip())
            if not tokenized: continue
            
            if tokenized not in signature_counts:
                signature_counts[tokenized] = set()
            signature_counts[tokenized].add(l["page"])
            
        boilerplate_tokens = {tok for tok, pages in signature_counts.items() if len(pages) >= occurrence_limit}
        
        # Purge matches from our line matrix arrays
        filtered_lines = []
        for l in self.raw_lines:
            tokenized = re.sub(r'\d+', '#', l["text"].lower().strip())
            if tokenized in boilerplate_tokens:
                continue
            filtered_lines.append(l)
            
        self.raw_lines = filtered_lines

   # =========================================================================
    # STAGE 3.5: COMPACT PARAGRAPH ASSEMBLY (REFINED SPLIT GATE)
    # =========================================================================
    def assemble_paragraphs(self):
        """
        Combines loose text elements into coherent paragraph arrays.
        FIXED: Uses a strict multiplier of the calibrated standard_gap to 
        ensure separate blocks are cleanly split rather than aggressively merged.
        """
        self.paragraphs = []
        if not self.raw_lines: return
        
        total_pages = max(l["page"] for l in self.raw_lines)
        
        # Strict geometric split gate: if the line gap exceeds 1.6x the natural 
        # line gap pattern of the document, it is a definitive paragraph split.
        line_gap_bound = self.metrics["standard_gap"] * 1.6
        
        for curr_page in range(1, total_pages + 1):
            page_lines = [l for l in self.raw_lines if l["page"] == curr_page]
            page_lines.sort(key=lambda x: x["top_y"]) # Read top-to-bottom
            
            current_paragraph = None
            for line in page_lines:
                if current_paragraph is None:
                    current_paragraph = {
                        "page": curr_page,
                        "text": line["text"],
                        "top_y": line["top_y"],
                        "bottom_y": line["bottom_y"]
                    }
                else:
                    gap = line["top_y"] - current_paragraph["bottom_y"]
                    
                    # If the gap falls within our tight standard text bounds, merge it
                    if 0 <= gap <= line_gap_bound:
                        current_paragraph["text"] = f"{current_paragraph['text']} {line['text']}".strip()
                        current_paragraph["bottom_y"] = line["bottom_y"]
                    else:
                        # Gap is wider than the baseline line-to-line spacing -> SPLIT!
                        self.paragraphs.append(current_paragraph)
                        current_paragraph = {
                            "page": curr_page,
                            "text": line["text"],
                            "top_y": line["top_y"],
                            "bottom_y": line["bottom_y"]
                        }
            if current_paragraph:
                self.paragraphs.append(current_paragraph)
                
        print(f"📝 [PARAGRAPH] Assembled remaining raw lines into {len(self.paragraphs)} clean textual blocks.")
    # =========================================================================
    # STAGE 4: MONOLITHIC STRUCTURAL TABLE STITCHING ENGINE
    # =========================================================================
    def stitch_structural_tables(self):
        """Stitches grid matrices using strict layout congruence gates and content verification."""
        self.final_tables = []
        header_limit = self.metrics["avg_line_height"] * 4
        
        for t in self.raw_tables:
            if not self.final_tables:
                self.final_tables.append(t)
                continue
                
            prev_t = self.final_tables[-1]
            
            # GATE A: Column size structure alignment check
            if len(t["rows"][0]) == len(prev_t["rows"][0]):
                # GATE B: Sequential page progression boundaries check
                if t["page"] == prev_t["last_page"] + 1 or t["page"] == prev_t["last_page"]:
                    
                    # GATE C: Verify if any true text paragraph is wedged between them
                    has_intervening_text = False
                    for p in self.paragraphs:
                        if prev_t["last_page"] == t["page"] == p["page"]:
                            if prev_t["bottom_y"] < p["top_y"] and p["bottom_y"] < t["top_y"]:
                                has_intervening_text = True
                                break
                        elif prev_t["last_page"] == p["page"] and p["top_y"] > prev_t["bottom_y"]:
                            has_intervening_text = True
                            break
                        elif t["page"] == p["page"] and p["bottom_y"] < t["top_y"]:
                            # Skip standard running header leftovers near page margins
                            if p["bottom_y"] > header_limit:
                                has_intervening_text = True
                                break
                                
                    if not has_intervening_text:
                        # Clear to merge. If the top row is a repeated header layout, drop it.
                        start_idx = 1 if t["rows"][0] == prev_t["rows"][0] else 0
                        prev_t["rows"].extend(t["rows"][start_idx:])
                        
                        if t["page"] not in prev_t["pages"]:
                            prev_t["pages"].append(t["page"])
                        prev_t["last_page"] = t["page"]
                        prev_t["bottom_y"] = t["bottom_y"]
                        continue
                        
            self.final_tables.append(t)

    # =========================================================================
    # STAGE 5: SYSTEM UNIFIED EXPORTER
    # =========================================================================
    def export_verification_json(self, output_base_dir="outputs"):
        """Saves one consolidated structural master JSON payload for review."""
        doc_dir = os.path.join(output_base_dir, self.doc_id)
        os.makedirs(doc_dir, exist_ok=True)
        
        # Pure decoupled master layout payload
        master_output = {
            "document_id": self.doc_id,
            "calibrated_metrics": self.metrics,
            "extracted_tables": [
                {
                    "table_id": t["table_id"],
                    "pages_spanned": t["pages"],
                    "bbox_coordinates": t["bbox"],
                    "data_matrix": t["rows"]
                } for t in self.final_tables
            ],
            "extracted_paragraphs": [
                {
                    "page": p["page"],
                    "text": p["text"]
                } for p in self.paragraphs
            ]
        }
        
        out_path = os.path.join(doc_dir, "extracted_blueprint.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(master_output, f, indent=2, ensure_ascii=False)
        print(f"🏁 Saved clean blueprint target for verification: {out_path}")

# =========================================================================
# RUNNER COUPLING ENGINE
# =========================================================================
if __name__ == "__main__":
    PDF_DIRECTORY = "pdf"
    if os.path.exists(PDF_DIRECTORY):
        pdf_files = [f for f in os.listdir(PDF_DIRECTORY) if f.lower().endswith(".pdf")]
        if pdf_files:
            print(f"📂 Found {len(pdf_files)} PDF target files.\n")
            for pdf_file in pdf_files:
                full_path = os.path.join(PDF_DIRECTORY, pdf_file)
                
                parser = GeneralizedDDParser(full_path)
                parser.calibrate_document_geometry() # Stage 1
                parser.extract_raw_components()       # Stage 2
                parser.remove_boilerplate_noise()     # Stage 3
                parser.assemble_paragraphs()          # Stage 3.5
                parser.stitch_structural_tables()     # Stage 4
                parser.export_verification_json()     # Stage 5
                print("-" * 70)