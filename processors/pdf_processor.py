import pdfplumber
import os

class PDFDataDictionaryProcessor:
    def __init__(self, pdf_path):
        self.pdf_path = pdf_path
        self.doc_id = os.path.splitext(os.path.basename(pdf_path))[0]

    def _clean_and_condense_table(self, raw_matrix):
        """
        Fixes Gap 2 (Ghost Columns) and Gap 3 (Row Splintering).
        Cleans empty columns and fuses wrapped multi-line cells back into single rows.
        """
        if not raw_matrix:
            return []
        
        # Standardize cell content and strip whitespace
        matrix = [[str(cell).strip() if cell is not None else "" for cell in row] for row in raw_matrix]
        
        # --- FIX GAP 2: DROP GHOST COLUMNS ---
        num_cols = len(matrix[0])
        ghost_cols = [c for c in range(num_cols) if all(row[c] == "" for row in matrix)]
        
        if ghost_cols:
            matrix = [[row[i] for i in range(num_cols) if i not in ghost_cols] for row in matrix]
            
        if not matrix:
            return []
            
        # --- FIX GAP 3: CONDENSE WRAPPED SPREAD ROWS ---
        condensed_matrix = []
        for row in matrix:
            if not any(row): 
                continue # Ignore completely empty rows
            
            # If the primary identifier cell (col 0) is empty but other cells have content,
            # this row is a continuation of the previous row.
            is_continuation = False
            if condensed_matrix and len(row) == len(condensed_matrix[-1]):
                if row[0] == "" and any(row[i] != "" for i in range(1, len(row))):
                    is_continuation = True
                    
            if is_continuation:
                # Append content to the preceding row's cells using newline boundaries
                for i in range(len(row)):
                    if row[i]:
                        if condensed_matrix[-1][i]:
                            condensed_matrix[-1][i] += f"\n{row[i]}"
                        else:
                            condensed_matrix[-1][i] = row[i]
            else:
                condensed_matrix.append(row)
                
        return condensed_matrix

    def process(self):
        print(f"📥 Extracting refined chronological layout from: {self.doc_id}.pdf")
        
        blueprint = {
            "document_id": self.doc_id,
            "source_format": ".pdf",
            "total_pages": 0,
            "pages": []
        }

        with pdfplumber.open(self.pdf_path) as pdf:
            blueprint["total_pages"] = len(pdf.pages)
            
            for page_num, page in enumerate(pdf.pages, start=1):
                page_elements = []
                
                # 1. Parse and clean tables first
                tables = page.find_tables()
                for t_idx, table in enumerate(tables):
                    raw_matrix = table.extract()
                    cleaned_matrix = self._clean_and_condense_table(raw_matrix)
                    
                    if cleaned_matrix:
                        bbox = [float(coord) for coord in table.bbox]
                        page_elements.append({
                            "type": "table",
                            "bbox": bbox,
                            "vertical_position_ratio": round(bbox[1] / page.height, 4),
                            "raw_matrix": cleaned_matrix
                        })

                # 2. Extract words and group them horizontally into rows
                words = page.extract_words()
                lines_dict = {}
                for w in words:
                    approx_top = round(w["top"])
                    matched = False
                    for existing_top in lines_dict.keys():
                        if abs(approx_top - existing_top) <= 3:
                            lines_dict[existing_top].append(w)
                            matched = True
                            break
                    if not matched:
                        lines_dict[approx_top] = [w]

                # 3. --- FIX GAP 1: SPLIT HORIZONTAL LINES BY WHITESPACE GAPS ---
                for top in sorted(lines_dict.keys()):
                    line_words = lines_dict[top]
                    line_words.sort(key=lambda x: x["x0"])
                    
                    if not line_words:
                        continue
                        
                    # Split words into distinct text blocks if horizontal gap > 40 pixels
                    word_segments = []
                    current_segment = [line_words[0]]
                    
                    for w in line_words[1:]:
                        horizontal_gap = w["x0"] - current_segment[-1]["x1"]
                        if horizontal_gap > 40.0:
                            word_segments.append(current_segment)
                            current_segment = [w]
                        else:
                            current_segment.append(w)
                    word_segments.append(current_segment)
                    
                    # Create independent layout elements for each text segment
                    for seg in word_segments:
                        text_line = " ".join([w['text'] for w in seg]).strip()
                        if not text_line:
                            continue
                            
                        min_x = float(min(w["x0"] for w in seg))
                        min_t = float(min(w["top"] for w in seg))
                        max_x = float(max(w["x1"] for w in seg))
                        max_b = float(max(w["bottom"] for w in seg))
                        
                        # Filter out text lines that duplicate table cell values
                        is_inside_table = False
                        for elem in page_elements:
                            if elem["type"] == "table":
                                t_bbox = elem["bbox"]
                                if min_t >= (t_bbox[1] - 2) and max_b <= (t_bbox[3] + 2):
                                    is_inside_table = True
                                    break
                                    
                        if is_inside_table:
                            continue

                        page_elements.append({
                            "type": "text_line",
                            "bbox": [min_x, min_t, max_x, max_b],
                            "vertical_position_ratio": round(min_t / page.height, 4),
                            "text": text_line
                        })

                # Sort all elements by vertical position to ensure linear reading flow
                page_elements.sort(key=lambda x: x["bbox"][1])
                
                for e_idx, elem in enumerate(page_elements):
                    elem["element_id"] = f"p{page_num}_e{e_idx}"

                blueprint["pages"].append({
                    "page_number": page_num,
                    "page_height": float(page.height),
                    "page_width": float(page.width),
                    "elements": page_elements
                })

        return blueprint