import numpy as np
import os

class TableAndParaStitcher:
    def __init__(self, step2_data):
        """
        STAGE 3: Statistical Paragraph Assembly & Continuous Table Inversion.
        Flattens physical page boundaries into a single unified chronological 
        document timeline using automated line spacing calibration.
        """
        self.blueprint = step2_data
        self.pages = step2_data.get("pages", [])
        self.doc_id = step2_data.get("document_id")

    def _calculate_dynamic_spacing_threshold(self):
        """
        Performs Document-Wide Statistical Fingerprinting.
        Analyzes spacing deltas across all text lines to isolate inner paragraph 
        gaps from hard block changes.
        """
        gaps = []
        for page in self.pages:
            lines = [e for e in page["elements"] if e["type"] == "text_line"]
            for i in range(len(lines) - 1):
                # Distance = Top Y of next line - Bottom Y of current line
                gap = lines[i+1]["bbox"][1] - lines[i]["bbox"][3]
                if 0 < gap < 40: # Filter out major section jumps or table skips
                    gaps.append(gap)

        if len(gaps) < 4:
            print("  ⚠️  Low text distribution density. Falling back to layout standard spacing (8.0px).")
            return 8.0

        gaps = sorted(gaps)
        # Isolate lower cluster median (inner line spacing) vs upper cluster median (block gaps)
        inner_line_gap = gaps[int(len(gaps) * 0.25)]
        block_gap = gaps[int(len(gaps) * 0.75)]
        
        dynamic_threshold = (inner_line_gap + block_gap) / 2.0
        # Ensure guardrail boundaries to keep threshold realistic
        return max(4.0, min(dynamic_threshold, 15.0))

    def _global_column_null_sweep(self, matrix):
        """
        Executes your global sweep logic. If a column track contains 100% empty strings 
        across every single row (header + data), it is dropped as a false canvas artifact.
        """
        if not matrix or not matrix[0]:
            return matrix
            
        num_cols = len(matrix[0])
        keep_indices = []
        
        for c in range(num_cols):
            # Check if there is data anywhere in this column track across all rows
            column_has_data = any(str(row[c]).strip() != "" for row in matrix)
            if column_has_data:
                keep_indices.append(c)
                
        # Rebuild the table matrix using only valid data columns
        cleaned_matrix = [[row[i] for i in keep_indices] for row in matrix]
        return cleaned_matrix

    def execute_processing(self):
        print(f"🧬 Calibrating dynamic layout models for document: {self.doc_id}")
        spacing_threshold = self._calculate_dynamic_spacing_threshold()
        print(f"📊 Statistical Line-Gap Threshold locked at: {spacing_threshold:.2f}px")

        global_elements = []
        global_counter = 0

        # --- PHASE 1: CHRONOLOGICAL PARAGRAPH ASSEMBLY (PAGE BY PAGE) ---
        for page in self.pages:
            p_num = page["page_number"]
            current_para = None

            for elem in page["elements"]:
                if elem["type"] == "table":
                    # If a table is encountered, close out any open paragraph text block
                    if current_para:
                        global_elements.append(current_para)
                        current_para = None
                    
                    global_elements.append({
                        "type": "table",
                        "pages_spanned": [p_num],
                        "bbox": elem["bbox"],
                        "raw_matrix": elem["raw_matrix"]
                    })

                elif elem["type"] == "text_line":
                    text_str = elem["text"].strip()
                    
                    # Protect explicit list tags or bullet characters from merging
                    is_bullet = text_str.startswith(('', '•', '-', '*', '▪'))
                    
                    if current_para and not is_bullet:
                        gap = elem["bbox"][1] - current_para["_last_b"]
                        left_alignment_delta = abs(elem["bbox"][0] - current_para["_initial_x0"])
                        
                        # FUSE CONDITIONS: 
                        # 1. Vertical space falls within the inner-paragraph threshold
                        # 2. Left margins (x0 coordinates) align precisely (within 4px)
                        if gap <= spacing_threshold and left_alignment_delta <= 4.0:
                            current_para["text"] += " " + text_str
                            current_para["_last_b"] = elem["bbox"][3] # Update bottom bound
                            continue
                    
                    # If conditions aren't met, finalize old paragraph and spawn a new one
                    if current_para:
                        global_elements.append(current_para)
                    
                    current_para = {
                        "type": "paragraph",
                        "text": text_str,
                        "_initial_x0": elem["bbox"][0],
                        "_last_b": elem["bbox"][3]
                    }

            if current_para:
                global_elements.append(current_para)

        # --- PHASE 2: CONTINUOUS MULTI-PAGE TABLE STITCHING ---
        stitched_elements = []
        
        for elem in global_elements:
            if not stitched_elements:
                stitched_elements.append(elem)
                continue
                
            prev_elem = stitched_elements[-1]
            
            # TRIGGER GATE: If consecutive blocks are both tables with no intervening text lines
            if prev_elem["type"] == "table" and elem["type"] == "table":
                matrix_a = prev_elem["raw_matrix"]
                matrix_b = elem["raw_matrix"]
                
                # Check if the column shapes line up structurally
                if matrix_a and matrix_b and len(matrix_a[0]) == len(matrix_b[0]):
                    start_row_idx = 0
                    
                    # If the incoming table repeats the identical header labels, skip it
                    if matrix_b[0] == matrix_a[0]:
                        start_row_idx = 1
                        
                    # Process rows and fuse split description fragments across page breaks
                    for r_idx in range(start_row_idx, len(matrix_b)):
                        row = matrix_b[r_idx]
                        
                        # SPLINTER DETECTION: Column 0 is blank, but descriptive text is present
                        if row[0] == "" and any(cell != "" for cell in row[1:]):
                            for col_c in range(len(row)):
                                if row[col_c]:
                                    # Append text directly to the preceding page's trailing row
                                    if prev_elem["raw_matrix"][-1][col_c]:
                                        prev_elem["raw_matrix"][-1][col_c] += "\n" + row[col_c]
                                    else:
                                        prev_elem["raw_matrix"][-1][col_c] = row[col_c]
                        else:
                            prev_elem["raw_matrix"].append(row)
                            
                    prev_elem["pages_spanned"].extend(elem["pages_spanned"])
                    continue

            stitched_elements.append(elem)

        # --- PHASE 3: GLOBAL COLUMN NULL SWEEP & CLEAN DISK WRITE ---
        final_document_timeline = []
        for elem in stitched_elements:
            block_data = {
                "element_id": f"global_block_{global_counter}",
                "type": elem["type"]
            }
            global_counter += 1
            
            if elem["type"] == "table":
                # Execute the final asset check sweep to drop dead tracking lanes
                cleaned_matrix = self._global_column_null_sweep(elem["raw_matrix"])
                block_data.update({
                    "pages_spanned": elem["pages_spanned"],
                    "raw_matrix": cleaned_matrix
                })
            else:
                block_data["text"] = elem["text"]
                
            final_document_timeline.append(block_data)

        return {
            "document_id": self.doc_id,
            "source_format": self.blueprint.get("source_format"),
            "total_pages": self.blueprint.get("total_pages"),
            "elements": final_document_timeline
        }