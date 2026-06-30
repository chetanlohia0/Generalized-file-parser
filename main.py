import os
import json
import subprocess
from processors.pdf_processor import PDFDataDictionaryProcessor
from processors.structured_processor import StructuredDataDictionaryProcessor
from processors.boilerplate_detector import BoilerplateDetector
from processors.table_and_para_stitcher import TableAndParaStitcher
from processors.llm_context_linker import LLMContextLinker

INPUT_DIRECTORY = "pdf"
OUTPUT_DIRECTORY = "outputs"

def convert_office_to_pdf(input_path, target_dir):
    print(f"🔄 Converting office document to vector PDF: {os.path.basename(input_path)}")
    try:
        cmd = [
            "soffice", "--headless", "--convert-to", "pdf",
            "--outdir", target_dir, input_path
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        target_pdf_name = os.path.splitext(os.path.basename(input_path))[0] + ".pdf"
        return os.path.join(target_dir, target_pdf_name)
    except Exception as e:
        print(f"  ❌ LibreOffice conversion failed: {e}. Ensure 'soffice' is in system PATH.")
        return None

def main():
    if not os.path.exists(INPUT_DIRECTORY):
        print(f"📁 Creating empty input folder: '{INPUT_DIRECTORY}/'. Drop your source files inside.")
        os.makedirs(INPUT_DIRECTORY, exist_ok=True)
        return

    all_files = [f for f in os.listdir(INPUT_DIRECTORY) if not f.startswith('.')]
    if not all_files:
        print(f"⚠️  No source target files detected inside '{INPUT_DIRECTORY}/'.")
        return

    print(f"🚀 Ingestion Framework Engaged. Executing local pipeline tracking...\n")

    for file_name in all_files:
        full_path = os.path.join(INPUT_DIRECTORY, file_name)
        doc_id, ext = os.path.splitext(file_name)
        ext = ext.lower()

        if os.path.getsize(full_path) == 0:
            print(f"⚠️  Skipping '{file_name}': File is empty.")
            continue

        doc_output_dir = os.path.join(OUTPUT_DIRECTORY, doc_id)
        os.makedirs(doc_output_dir, exist_ok=True)

        raw_layout_blueprint = None
        print(f"📦 Processing file track stream: {file_name}")

        try:
            # --- STEP 1: COMPONENT EXTRACTION ---
            if ext in ['.csv', '.xlsx', '.xls']:
                processor = StructuredDataDictionaryProcessor(full_path)
                raw_layout_blueprint = processor.process()
            elif ext in ['.pdf', '.docx', '.doc', '.pptx', '.ppt']:
                target_pdf = full_path
                is_converted = False
                if ext in ['.docx', '.doc', '.pptx', '.ppt']:
                    converted_pdf_path = convert_office_to_pdf(full_path, doc_output_dir)
                    if converted_pdf_path and os.path.exists(converted_pdf_path):
                        target_pdf = converted_pdf_path
                        is_converted = True
                    else:
                        continue
                processor = PDFDataDictionaryProcessor(target_pdf)
                raw_layout_blueprint = processor.process()
                if is_converted and os.path.exists(target_pdf):
                    os.remove(target_pdf)

            if raw_layout_blueprint:
                step1_output_path = os.path.join(doc_output_dir, "step1_raw_elements.json")
                with open(step1_output_path, "w", encoding="utf-8") as f:
                    json.dump(raw_layout_blueprint, f, indent=2, ensure_ascii=False)

                # --- STEP 2: NOISE ISOLATION ---
                detector = BoilerplateDetector(raw_layout_blueprint)
                stripped_blueprint, boilerplate_data = detector.detect_and_strip()
                
                boilerplate_path = os.path.join(doc_output_dir, "boilerplate.json")
                with open(boilerplate_path, "w", encoding="utf-8") as f:
                    json.dump(boilerplate_data, f, indent=2, ensure_ascii=False)

                step2_output_path = os.path.join(doc_output_dir, "step2_stripped_elements.json")
                with open(step2_output_path, "w", encoding="utf-8") as f:
                    json.dump(stripped_blueprint, f, indent=2, ensure_ascii=False)

                # --- STEP 3: LOGICAL STITCHING ---
                stitcher = TableAndParaStitcher(stripped_blueprint)
                gold_timeline_output = stitcher.execute_processing()

                step3_output_path = os.path.join(doc_output_dir, "step3_gold_elements.json")
                with open(step3_output_path, "w", encoding="utf-8") as f:
                    json.dump(gold_timeline_output, f, indent=2, ensure_ascii=False)

                # --- STEP 4: INTELLECTUAL LOCAL LLM CONTEXT LINKING ---
                linker = LLMContextLinker(gold_timeline_output)
                step4_context_output = linker.execute_linking()

                step4_output_path = os.path.join(doc_output_dir, "step4_context_linked.json")
                with open(step4_output_path, "w", encoding="utf-8") as f:
                    json.dump(step4_context_output, f, indent=2, ensure_ascii=False)

                print(f"✅ Step 4 Complete! Local LLM mapped timeline saved to: {step4_output_path}")
                print("=" * 80)

        except Exception as e:
            print(f"  ❌ Critical pipeline error parsing '{file_name}': {e}")
            continue

if __name__ == "__main__":
    main()