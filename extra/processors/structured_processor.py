import pandas as pd
import os

class StructuredDataDictionaryProcessor:
    def __init__(self, file_path):
        self.file_path = file_path
        self.doc_id = os.path.splitext(os.path.basename(file_path))[0]
        
    def process(self):
        """
        Direct database-style extraction for structured formats.
        Bypasses geometric coordinate math completely.
        """
        print(f"📊 Running Direct Grid Ingestion for: {self.doc_id}")
        ext = os.path.splitext(self.file_path)[1].lower()
        
        extracted_tables = []
        
        try:
            if ext == '.csv':
                df = pd.read_csv(self.file_path, keep_default_na=False)
                extracted_tables.append(self._convert_df_to_matrix(df, "csv_main_sheet"))
            elif ext in ['.xlsx', '.xls']:
                # Read all sheets inside an Excel workbook layout dynamically
                excel_file = pd.ExcelFile(self.file_path)
                for sheet_name in excel_file.sheet_names:
                    df = pd.read_excel(self.file_path, sheet_name=sheet_name, keep_default_na=False)
                    extracted_tables.append(self._convert_df_to_matrix(df, sheet_name))
        except Exception as e:
            print(f"  ❌ Error reading structured sheet: {e}")
            
        # Native grids do not contain disjoint floating paragraph lines
        return {
            "calibrated_metrics": {"message": "Native structured layout file. Geometry tracking bypassed."},
            "extracted_tables": extracted_tables,
            "extracted_paragraphs": []
        }
        
    def _convert_df_to_matrix(self, df, sheet_name):
        """Standardizes a Pandas DataFrame into our unified blueprint data matrix schema."""
        headers = [str(col).strip() for col in df.columns]
        data_matrix = [headers]
        
        for _, row in df.iterrows():
            matrix_row = [str(cell).strip() for cell in row]
            data_matrix.append(matrix_row)
            
        return {
            "table_id": f"structured_{sheet_name}",
            "pages_spanned": [1],
            "bbox_coordinates": [0, 0, 0, 0], # Matrix data holds no layout footprints
            "data_matrix": data_matrix
        }