import os
import json
import pdfplumber

INPUT_DIR = "pdf"
OUTPUT_DIR = "outputs_parser"

def setup():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

def extract_tables_from_pdf(pdf_path):
    base_name = os.path.splitext(os.path.basename(pdf_path))[0]
    
    with pdfplumber.open(pdf_path) as pdf:
        table_count = 0
        
        for page_num, page in enumerate(pdf.pages, start=1):
            # Find all tables on the current page
            tables = page.extract_tables()
            
            for table in tables:
                table_count += 1
                # Convert the list of lists into a more structured list of dicts (assuming row 0 is headers)
                if len(table) > 1:
                    headers = [str(h).replace("\n", " ").strip() if h else f"Col_{i}" for i, h in enumerate(table[0])]
                    structured_data = []
                    
                    for row in table[1:]:
                        row_dict = {}
                        for i, cell in enumerate(row):
                            header = headers[i] if i < len(headers) else f"Col_{i}"
                            row_dict[header] = str(cell).replace("\n", " ").strip() if cell else None
                        structured_data.append(row_dict)
                    
                    # Save to a unique JSON file
                    out_name = f"{base_name}_page{page_num}_table{table_count}.json"
                    out_path = os.path.join(OUTPUT_DIR, out_name)
                    
                    with open(out_path, "w", encoding="utf-8") as f:
                        json.dump({
                            "source_file": base_name,
                            "page": page_num,
                            "data": structured_data
                        }, f, indent=4)
                        
                    print(f"✅ Saved: {out_name}")

def main():
    print("=== APPROACH 1: NATIVE PDF PARSER ===")
    setup()
    
    for file in os.listdir(INPUT_DIR):
        if file.lower().endswith(".pdf"):
            print(f"\nProcessing: {file}")
            extract_tables_from_pdf(os.path.join(INPUT_DIR, file))

if __name__ == "__main__":
    main()