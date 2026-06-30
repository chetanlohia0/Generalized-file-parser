import pdfplumber
import numpy as np
import os
import re

class PDFDataDictionaryProcessor:
    def __init__(self, pdf_path):
        self.pdf_path = pdf_path
        self.doc_id = os.path.splitext(os.path.basename(pdf_path))[0]
        
        self.metrics = {"avg_line_height": 10.0, "standard_gap": 3.0, "calibration_successful": False}
        self.raw_tables = []
        self.raw_lines = []
        self.paragraphs = []
        self.final_tables = []

    # =========================================================================
    # STAGE 1: RAW ELEMENT EXTRACTION
    # =========================================================================
    def extract_raw_elements(self):
        """Extracts text streams and table elements cleanly into independent arrays."""
        self.raw_tables = []
        self.raw_lines = []
        
        # Compute baseline geometry bounds directly from raw page dimensions
        self._calibrate_geometry_from_canvas()
        
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
                        "page": page_num, "pages": [page_num], "last_page": page_num,
                        "bbox": bbox, "top_y": bbox[1], "bottom_y": bbox[3],
                        "rows": consolidated_data
                    }
                    self.raw_tables.append(table_meta)
                    page_tables_meta.append(table_meta)
                
                words = page.extract_words()
                lines_dict = {}
                for w in words:
                    approx_top = round(w["top"])
                    matched = False
                    for d_top in lines_dict.keys():
                        if abs(approx_top - d_top) <= 3:
                            lines_dict[d_top].append(w)
                            matched = True
                            break
                    if not matched: lines_dict[approx_top] = [w]
                        
                for top in sorted(lines_dict.keys()):
                    line_words = lines_dict[top]
                    text = " ".join([w['text'] for w in line_words]).strip()
                    min_t = min(w["top"] for w in line_words)
                    max_b = max(w["bottom"] for w in line_words)
                    
                    if any(min_t >= (t["top_y"] - 2) and max_b <= (t["bottom_y"] + 2) for t in page_tables_meta):
                        continue
                    
                    self.raw_lines.append({
                        "page": page_num, "text": text, "top_y": min_t, "bottom_y": max_b,
                        "rel_top_y": min_t / page.height
                    })

    # =========================================================================
    # STAGE 2: DYNAMIC TYPOGRAPHY CALIBRATION (REFINED)
    # =========================================================================
    def _calibrate_geometry_from_canvas(self):
        """Calculates line heights and line spacing footprints using narrative blocks."""
        line_heights = []
        line_gaps = []
        
        with pdfplumber.open(self.pdf_path) as pdf:
            for page in pdf.pages[:2]:
                table_bboxes = [t.bbox for t in page.find_tables()]
                words = page.extract_words()
                if not words: continue
                
                lines_dict = {}
                for w in words:
                    if any(w["top"] >= (b[1] - 2) and w["bottom"] <= (b[3] + 2) for b in table_bboxes):
                        continue
                    approx_top = round(w["top"])
                    matched = False
                    for d_top in lines_dict.keys():
                        if abs(approx_top - d_top) <= 3:
                            lines_dict[d_top].append(w)
                            matched = True
                            break
                    if not matched: lines_dict[approx_top] = [w]
                
                sorted_tops = sorted(lines_dict.keys())
                for i, top in enumerate(sorted_tops):
                    line_words = lines_dict[top]
                    max_b = max(w["bottom"] for w in line_words)
                    min_t = min(w["top"] for w in line_words)
                    line_heights.append(max_b - min_t)
                    if i > 0:
                        prev_b = max(w["bottom"] for w in lines_dict[sorted_tops[i-1]])
                        gap = min_t - prev_b
                        # Filter out blank areas to pinpoint the tight narrative font wrap signature
                        if 0 < gap < (max_b - min_t) * 0.6: 
                            line_gaps.append(gap)
                            
        if line_heights:
            self.metrics["avg_line_height"] = float(np.median(line_heights))
            self.metrics["standard_gap"] = float(np.percentile(line_gaps, 25)) if line_gaps else 2.5
            self.metrics["calibration_successful"] = True
        else:
            self.metrics["avg_line_height"] = 11.0
            self.metrics["standard_gap"] = 3.0
            
        print(f"🔬 Calibrated Geometry: Height={self.metrics['avg_line_height']:.2f}px, Gap={self.metrics['standard_gap']:.2f}px")

    # =========================================================================
    # STAGE 3: GLOBAL SPATIAL DE-NOISING
    # =========================================================================
    def remove_boilerplate_noise(self):
        if not self.raw_lines: return
        signature_counts = {}
        spatial_counts = {}
        
        for l in self.raw_lines:
            tokenized = re.sub(r'\d+', '#', l["text"].lower().strip())
            tokenized = re.sub(r'\s+', ' ', tokenized)
            if not tokenized: continue
            
            if tokenized not in signature_counts: signature_counts[tokenized] = set()
            signature_counts[tokenized].add(l["page"])
            
            spatial_key = (tokenized, round(l["rel_top_y"], 2))
            if spatial_key not in spatial_counts: spatial_counts[spatial_key] = set()
            spatial_counts[spatial_key].add(l["page"])
            
        boilerplate_tokens = {tok for tok, pages in signature_counts.items() if len(pages) >= 2 and len(tok) > 15}
        boilerplate_spatial = {key for key, pages in spatial_counts.items() if len(pages) >= 2}
        
        self.raw_lines = [
            l for l in self.raw_lines 
            if re.sub(r'\s+', ' ', re.sub(r'\d+', '#', l["text"].lower().strip())) not in boilerplate_tokens
            and (re.sub(r'\s+', ' ', re.sub(r'\d+', '#', l["text"].lower().strip())), round(l["rel_top_y"], 2)) not in boilerplate_spatial
        ]
        print(f"🧹 [DE-NOISE] Cleaned boilerplate elements from the raw stream.")

    # =========================================================================
    # STAGE 4: COMPACT PARAGRAPH ASSEMBLY
    # =========================================================================
    def assemble_paragraphs(self):
        self.paragraphs = []
        if not self.raw_lines: return
        total_pages = max(l["page"] for l in self.raw_lines)
        
        line_gap_bound = max(self.metrics["standard_gap"] * 2.5, self.metrics["avg_line_height"] * 0.65)
        
        for curr_page in range(1, total_pages + 1):
            page_lines = sorted([l for l in self.raw_lines if l["page"] == curr_page], key=lambda x: x["top_y"])
            current_paragraph = None
            for line in page_lines:
                is_list_start = re.match(r'^([•\*\-\u2022\u25b6\u25ba]|\d+\.|\w\.)', line["text"].strip())
                
                if current_paragraph is None:
                    current_paragraph = {
                        "page": curr_page, "text": line["text"], 
                        "top_y": line["top_y"], "bottom_y": line["bottom_y"],
                        "rel_top_y": line["rel_top_y"]
                    }
                else:
                    gap = line["top_y"] - current_paragraph["bottom_y"]
                    if 0 <= gap <= line_gap_bound and not is_list_start:
                        current_paragraph["text"] = f"{current_paragraph['text']} {line['text']}".strip()
                        current_paragraph["bottom_y"] = line["bottom_y"]
                    else:
                        self.paragraphs.append(current_paragraph)
                        current_paragraph = {
                            "page": curr_page, "text": line["text"], 
                            "top_y": line["top_y"], "bottom_y": line["bottom_y"],
                            "rel_top_y": line["rel_top_y"]
                        }
            if current_paragraph: self.paragraphs.append(current_paragraph)

    # =========================================================================
    # STAGE 5: GENERALIZED MATRICES RECONSTRUCTION
    # =========================================================================
    def _fuse_multiline_headers(self, matrix):
        """
        💡 GENERALIZED SOLUTION FOR BUG A (No Hardcoded Keywords):
        Evaluates structural variance and primary key sequencing indices to 
        safely unify multi-line stacked headers.
        """
        if len(matrix) < 2: return matrix
        
        first_cell_clean = str(matrix[1][0]).strip()
        
        # Gate Validation check: If row 1 begins with a sequential index integer 
        # (like '1', '2') or a standard schema ID pattern, it is a true data row. Abort fusion!
        is_data_start = re.match(r'^(\d+|[a-zA-Z]+\d+)', first_cell_clean)
        
        if not is_data_start:
            # Structurally fuse elements downward into the primary tracking index
            fused_header = []
            for col_idx in range(len(matrix[0])):
                c1 = matrix[0][col_idx].strip()
                c2 = matrix[1][col_idx].strip()
                if c1 == c2: fused_header.append(c1)
                elif c1 == "": fused_header.append(c2)
                elif c2 == "": fused_header.append(c1)
                else: fused_header.append(f"{c1} {c2}".strip().replace("\n", " "))
            matrix[0] = fused_header
            matrix.pop(1) # Wipe the secondary placeholder layout line row segment
            
        return matrix

    def _compress_ghost_columns(self, matrix):
        if not matrix or len(matrix[0]) <= 1: return matrix
        col = 0
        while col < len(matrix[0]) - 1:
            can_merge = True
            all_blank_col = True
            all_blank_next = True
            
            for row_idx in range(1, len(matrix)):
                if col + 1 >= len(matrix[row_idx]):
                    can_merge = False
                    break
                val1 = matrix[row_idx][col].strip()
                val2 = matrix[row_idx][col+1].strip()
                
                if val1 != "": all_blank_col = False
                if val2 != "": all_blank_next = False
                if val1 != "" and val2 != "" and val1 != val2:
                    can_merge = False
                    break
            
            if (can_merge and (not all_blank_col or not all_blank_next)) or all_blank_col or all_blank_next:
                for row_idx in range(len(matrix)):
                    if col + 1 >= len(matrix[row_idx]): continue
                    h1 = matrix[row_idx][col].strip()
                    h2 = matrix[row_idx][col+1].strip()
                    if h1 == h2: matrix[row_idx][col] = h1
                    elif h1 == "": matrix[row_idx][col] = h2
                    elif h2 == "": matrix[row_idx][col] = h1
                    else: matrix[row_idx][col] = f"{h1}\n{h2}".strip()
                        
                for row_idx in range(len(matrix)):
                    if col + 1 < len(matrix[row_idx]):
                        matrix[row_idx].pop(col+1)
            else:
                col += 1
        return matrix

    def _consolidate_rows(self, raw_rows):
        cleaned_rows = []
        for raw_row in raw_rows:
            row = [str(cell).strip() if cell else "" for cell in raw_row]
            if not any(row): continue
                
            if not row[0] and cleaned_rows:
                for i in range(len(row)):
                    if row[i]:
                        if cleaned_rows[-1][i]:
                            cleaned_rows[-1][i] = f"{cleaned_rows[-1][i]}\n{row[i]}".strip()
                        else:
                            cleaned_rows[-1][i] = row[i]
            else:
                cleaned_rows.append(row)
                
        fused_matrix = self._fuse_multiline_headers(cleaned_rows)
        return self._compress_ghost_columns(fused_matrix)

    def stitch_structural_tables(self):
        self.final_tables = []
        header_limit = self.metrics["avg_line_height"] * 4
        
        for t in self.raw_tables:
            if not self.final_tables:
                self.final_tables.append(t)
                continue
                
            prev_t = self.final_tables[-1]
            
            if len(t["rows"][0]) == len(prev_t["rows"][0]):
                if t["page"] in [prev_t["last_page"], prev_t["last_page"] + 1]:
                    
                    has_intervening_text = False
                    for p in self.paragraphs:
                        if prev_t["last_page"] == t["page"] == p["page"]:
                            if prev_t["bottom_y"] < p["top_y"] and p["bottom_y"] < t["top_y"]:
                                has_intervening_text = True
                                break
                        elif prev_t["last_page"] == p["page"] and p["top_y"] > prev_t["bottom_y"]:
                            has_intervening_text = True
                            break
                        elif t["page"] == p["page"] and p["bottom_y"] < t["top_y"] and p["bottom_y"] > header_limit:
                            has_intervening_text = True
                            break
                                
                    if not has_intervening_text:
                        header_rows_to_strip = 0
                        max_header_check = min(len(t["rows"]), 5)
                        for r_idx in range(max_header_check):
                            if t["rows"][r_idx] == prev_t["rows"][r_idx]:
                                header_rows_to_strip = r_idx + 1
                            else:
                                break
                        
                        incoming_rows = t["rows"][header_rows_to_strip:]
                        
                        if incoming_rows and not incoming_rows[0][0] and prev_t["rows"]:
                            fragment_row = incoming_rows[0]
                            for i in range(len(fragment_row)):
                                if fragment_row[i]:
                                    prev_t["rows"][-1][i] = f"{prev_t['rows'][-1][i]}\n{fragment_row[i]}".strip()
                            incoming_rows = incoming_rows[1:]
                        
                        prev_t["rows"].extend(incoming_rows)
                        if t["page"] not in prev_t["pages"]: prev_t["pages"].append(t["page"])
                        prev_t["last_page"] = t["page"]
                        prev_t["bottom_y"] = t["bottom_y"]
                        continue
                        
            self.final_tables.append(t)

    def process(self):
            self.extract_raw_elements()
            self.remove_boilerplate_noise()
            self.assemble_paragraphs()
            self.stitch_structural_tables()
            # 💡 NOTE: We removed attach_context from here! This file now does PURE structural extraction.
            
            return {
                "document_id": self.doc_id,
                "calibrated_metrics": self.metrics,
                "extracted_tables": [
                    {
                        "table_id": t["table_id"],
                        "page": t["page"],
                        "pages_spanned": t["pages"],
                        "last_page": t["last_page"],
                        "bbox_coordinates": t["bbox"],
                        "top_y": t["top_y"],
                        "bottom_y": t["bottom_y"],
                        "data_matrix": t["rows"]
                    } for t in self.final_tables
                ],
                # 💡 UPGRADE: Retain coordinates so downstream modules can compute spatial envelopes offline
                "extracted_paragraphs": [
                    {
                        "page": p["page"],
                        "text": p["text"],
                        "top_y": p["top_y"],
                        "bottom_y": p["bottom_y"],
                        "rel_top_y": p["rel_top_y"],
                        "assigned": False
                    } for p in self.paragraphs
                ]
            }