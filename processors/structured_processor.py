import pandas as pd
import os

class StructuredDataDictionaryProcessor:
    def __init__(self, file_path):
        self.file_path = file_path
        self.doc_id = os.path.splitext(os.path.basename(file_path))[0]
        
    def process(self):
        print(f"📊 Running Direct Grid Ingestion for Structured File: {self.doc_id}")
        ext = os.path.splitext(self.file_path)[1].lower()
        
        blueprint = {
            "document_id": self.doc_id,
            "source_format": ext,
            "total_pages": 0,
            "pages": []
        }
        
        try:
            if ext == '.csv':
                df = pd.read_csv(self.file_path, keep_default_na=False)
                blueprint["total_pages"] = 1
                blueprint["pages"].append(self._create_pseudo_page(df, "csv_main_sheet", 1))
            elif ext in ['.xlsx', '.xls']:
                excel_file = pd.ExcelFile(self.file_path)
                blueprint["total_pages"] = len(excel_file.sheet_names)
                for s_idx, sheet_name in enumerate(excel_file.sheet_names, start=1):
                    df = pd.read_excel(self.file_path, sheet_name=sheet_name, keep_default_na=False)
                    blueprint["pages"].append(self._create_pseudo_page(df, sheet_name, s_idx))
        except Exception as e:
            print(f"  ❌ Error reading structured file: {e}")
            
        return blueprint
        
    def _create_pseudo_page(self, df, sheet_name, page_num):
        headers = [str(col).strip() for col in df.columns]
        data_matrix = [headers]
        
        for _, row in df.iterrows():
            matrix_row = [str(cell).strip() for cell in row]
            data_matrix.append(matrix_row)
            
        return {
            "page_number": page_num,
            "page_height": 0.0,
            "page_width": 0.0,
            "elements": [
                {
                    "element_id": f"p{page_num}_e0",
                    "type": "table",
                    "bbox": [0.0, 0.0, 0.0, 0.0],
                    "vertical_position_ratio": 0.0,
                    "sheet_name": sheet_name,
                    "raw_matrix": data_matrix
                }
            ]
        }