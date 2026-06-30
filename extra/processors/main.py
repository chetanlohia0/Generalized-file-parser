import os
import json
import subprocess
from extra.processors.pdf_processor import PDFDataDictionaryProcessor
from extra.processors.structured_processor import StructuredDataDictionaryProcessor
from extra.processors.context_linker import BoundedContextLinkerEngine

INPUT_DIRECTORY = "pdf"
OUTPUT_DIRECTORY = "outputs"

def convert_to_pdf_via_libreoffice(input_path, target_dir):
    """
    Programmatic helper to convert visual office docs (.docx, .pptx) into 
    high-fidelity PDFs, leveraging a headless local LibreOffice installation.
    """
    print(f"🔄 Converting office document to PDF format: {os.path.basename(input_path)}")
    try:
        cmd = [
            "soffice", "--headless", "--convert-to", "pdf",
            "--outdir", target_dir, input_path
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        target_pdf_name = os.path.splitext(os.path.basename(input_path))[0] + ".pdf"
        return os.path.join(target_dir, target_pdf_name)
    except Exception as e:
        print(f"  ❌ LibreOffice conversion failed: {e}. Ensure 'soffice' is in your system PATH.")
        return None
def main():
    if not os.path.exists(INPUT_DIRECTORY):
        print(f"📁 Creating empty input folder: '{INPUT_DIRECTORY}/'. Drop your source layouts inside.")
        os.makedirs(INPUT_DIRECTORY, exist_ok=True)
        return

    # Dynamic file inventory fetch
    all_files = [f for f in os.listdir(INPUT_DIRECTORY) if not f.startswith('.')]
    if not all_files:
        print(f"⚠️  No data layout target files detected inside '{INPUT_DIRECTORY}/'.")
        return

    print(f"🚀 Master Ingestion Router running. Found {len(all_files)} document(s) for extraction.\n")

    for file_name in all_files:
        full_path = os.path.join(INPUT_DIRECTORY, file_name)
        doc_id, ext = os.path.splitext(file_name)
        ext = ext.lower()

        # GUARD CHECK: Skip empty files immediately (prevents empty file crashing)
        if os.path.getsize(full_path) == 0:
            print(f"⚠️  Skipping '{file_name}': File is completely empty (0 bytes).")
            continue

        # Provision a dedicated directory path for this specific document target
        doc_output_dir = os.path.join(OUTPUT_DIRECTORY, doc_id)
        os.makedirs(doc_output_dir, exist_ok=True)

        blueprint_output = None
        temp_pdf_path = None

        # Trace block execution state step by step
        print(f"🔄 Processing file: {file_name}")

        # --- ROUTING GATE ENGINE WITH RUNTIME SAFETY BOUNDARIES ---
# --- ROUTING GATE ENGINE WITH RUNTIME SAFETY BOUNDARIES ---
        try:
            if ext in ['.docx', '.doc', '.ppt', '.pptx']:
                temp_pdf_path = convert_to_pdf_via_libreoffice(full_path, doc_output_dir)
                if temp_pdf_path and os.path.exists(temp_pdf_path) and os.path.getsize(temp_pdf_path) > 0:
                    processor = PDFDataDictionaryProcessor(temp_pdf_path)
                    raw_layout_output = processor.process()
                    os.remove(temp_pdf_path)
                else:
                    print(f"  ❌ Conversion failed for: {file_name}")
                    continue

            elif ext == '.pdf':
                processor = PDFDataDictionaryProcessor(full_path)
                raw_layout_output = processor.process() # STAGE 1: Visual Layout Extraction

            elif ext in ['.csv', '.xlsx', '.xls']:
                processor = StructuredDataDictionaryProcessor(full_path)
                raw_layout_output = processor.process()

            else:
                print(f"⚠️  Skipping unsupported format type layout: {file_name}")
                continue

            # --- STAGE 2: STANDALONE SEMANTIC CONTEXT LINKER PASS ---
            if raw_layout_output:
                # Initialize the brand new standalone text connection engine
                linker = BoundedContextLinkerEngine(raw_layout_output)
                final_blueprint_output = linker.execute_strategy_1_linking() # STAGE 2 Executes here!

        except Exception as e:
            print(f"  ❌ Critical pipeline extraction error on '{file_name}': {e}")
            continue

        # --- UNIFIED EXPORT GENERATION ---
        if final_blueprint_output:
            master_json_path = os.path.join(doc_output_dir, "extracted_blueprint.json")
            with open(master_json_path, "w", encoding="utf-8") as f:
                json.dump(final_blueprint_output, f, indent=2, ensure_ascii=False)
            print(f"🏁 Standardized Blueprint successfully written to: {master_json_path}")
            print("=" * 75)

        # --- UNIFIED EXPORT GENERATION ---
        if final_blueprint_output:
            master_json_path = os.path.join(doc_output_dir, "extracted_blueprint.json")
            with open(master_json_path, "w", encoding="utf-8") as f:
                json.dump(final_blueprint_output, f, indent=2, ensure_ascii=False)
            print(f"🏁 Standardized Blueprint successfully written to: {master_json_path}")
            print("=" * 75)

        # --- UNIFIED EXPORT GENERATION ---
        if blueprint_output:
            master_json_path = os.path.join(doc_output_dir, "extracted_blueprint.json")
            with open(master_json_path, "w", encoding="utf-8") as f:
                json.dump(blueprint_output, f, indent=2, ensure_ascii=False)
            print(f"🏁 Standardized Blueprint successfully written to: {master_json_path}")
            print("=" * 75)

if __name__ == "__main__":
    main()