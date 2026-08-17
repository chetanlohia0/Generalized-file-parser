import os
import shutil
import cv2
import json
import numpy as np
import google.generativeai as genai
from pdf2image import convert_from_path
from ultralytics import YOLO

# --- CONFIGURATION ---
INPUT_DIR = "pdf"
OUT_BASE = "outputs_yolo"
DIRS = {
    "images": os.path.join(OUT_BASE, "0_images"),
    "annotated": os.path.join(OUT_BASE, "1_annotated"),
    "cropped": os.path.join(OUT_BASE, "2_cropped"),
    "json": os.path.join(OUT_BASE, "3_final_json"),
}
MODEL_PATH = os.path.join("finetunedmodel", "weights", "best.pt")

CROP_PADDING_PCT = 0.04  # 4% padding 

# Set your API Key


os.environ["GEMINI_API_KEY"] = "<API KEY>"  # Replace or load from env
genai.configure(api_key=os.environ["GEMINI_API_KEY"])
vlm_model = genai.GenerativeModel("gemini-2.5-flash")

# ─────────────────────────────
# GEOMETRY & CLUSTERING LOGIC
# ─────────────────────────────
def area(box):
    return max(0, box[2]-box[0]) * max(0, box[3]-box[1])

def intersection(box1, box2):
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])
    return max(0, x2-x1) * max(0, y2-y1)

def iou(box1, box2):
    inter = intersection(box1, box2)
    return inter / (area(box1) + area(box2) - inter + 1e-6)

def merge_boxes(boxes):
    return [
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    ]

def cluster_elements(elements, cls_name, iou_thresh=0.25):
    """Merges overlapping YOLO bounding boxes of the same class."""
    filtered = [d for d in elements if d["class"] == cls_name]
    if not filtered: return []
    
    clusters = []
    for el in filtered:
        added = False
        for c in clusters:
            for member in c:
                if iou(el["bbox"], member["bbox"]) > iou_thresh:
                    c.append(el)
                    added = True
                    break
            if added: break
        if not added:
            clusters.append([el])
            
    merged = []
    for c in clusters:
        bboxes = [m["bbox"] for m in c]
        merged.append({
            "class": cls_name,
            "bbox": merge_boxes(bboxes),
            "members": bboxes 
        })
    return merged

# ─────────────────────────────
# MASKED & PADDED CROP
# ─────────────────────────────
def masked_crop_padded(img, merged_bbox, member_bboxes, pad_pct=0.04):
    """
    Creates a clean white canvas of the padded bounding box size,
    then copies ONLY the pixels from the padded member sub-regions onto it.
    """
    img_h, img_w = img.shape[:2]
    mx1, my1, mx2, my2 = merged_bbox
    
    # 1. Pad the main canvas bounds
    pad_x = (mx2 - mx1) * pad_pct
    pad_y = (my2 - my1) * pad_pct

    px1 = max(0, int(mx1 - pad_x))
    py1 = max(0, int(my1 - pad_y))
    px2 = min(img_w, int(mx2 + pad_x))
    py2 = min(img_h, int(my2 + pad_y))
    
    # Create white canvas
    cw, ch = px2 - px1, py2 - py1
    if cw <= 0 or ch <= 0: return None
    canvas = np.ones((ch, cw, 3), dtype=np.uint8) * 255
    
    # 2. Paste members (also padded slightly to capture their outer table borders)
    for mb in member_bboxes:
        bx1, by1, bx2, by2 = mb
        
        bpad_x = (bx2 - bx1) * pad_pct
        bpad_y = (by2 - by1) * pad_pct

        c_x1 = max(0, int(bx1 - bpad_x))
        c_y1 = max(0, int(by1 - bpad_y))
        c_x2 = min(img_w, int(bx2 + bpad_x))
        c_y2 = min(img_h, int(by2 + bpad_y))
        
        sub_crop = img[c_y1:c_y2, c_x1:c_x2]
        if sub_crop.size == 0: continue
            
        # Coordinates for where to paste this member onto the canvas
        paste_x1 = c_x1 - px1
        paste_y1 = c_y1 - py1
        paste_x2 = paste_x1 + (c_x2 - c_x1)
        paste_y2 = paste_y1 + (c_y2 - c_y1)
        
        canvas[paste_y1:paste_y2, paste_x1:paste_x2] = sub_crop
        
    return canvas

# ─────────────────────────────
# MAIN PIPELINE
# ─────────────────────────────
def setup_dirs():
    print("   -> Cleaning output directories...")
    for d in DIRS.values():
        if os.path.exists(d):
            shutil.rmtree(d)
        os.makedirs(d)

def extract_table_json_with_gemini(image_path, out_json_path):
    prompt = """
    Extract the tabular data from this image. 
    Return a STRICT JSON array of objects. 
    Use the column headers from the table as the JSON keys. 
    Do not include markdown blocks like ```json, just return the raw JSON array.
    """
    try:
        import PIL.Image
        img = PIL.Image.open(image_path)
        response = vlm_model.generate_content([prompt, img])
        
        raw_text = response.text.strip()
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:-3].strip()
            
        data = json.loads(raw_text)
        
        with open(out_json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        return True
    except Exception as e:
        print(f"      ❌ Gemini Extraction Failed: {e}")
        return False

def main():
    print("=== APPROACH 2: YOLO + GEMINI VISION ===")
    setup_dirs()
    yolo_model = YOLO(MODEL_PATH)

    for file in os.listdir(INPUT_DIR):
        if not file.lower().endswith(".pdf"):
            continue
            
        pdf_path = os.path.join(INPUT_DIR, file)
        base_name = os.path.splitext(file)[0]
        print(f"\n📄 Processing PDF: {file}")

        print("   -> Converting PDF pages to images...")
        pages = convert_from_path(pdf_path, dpi=200) 
        
        for page_num, page_img in enumerate(pages, start=1):
            img_name = f"{base_name}_page{page_num}.png"
            img_path = os.path.join(DIRS["images"], img_name)
            page_img.save(img_path, "PNG")
            
            # 1. Run YOLO
            cv_img = cv2.imread(img_path)
            results = yolo_model(img_path, conf=0.25, verbose=False)[0]
            
            # 2. Collect Detections
            detections = []
            for box in results.boxes:
                cls_name = yolo_model.names[int(box.cls[0])]
                if cls_name == "table":
                    detections.append({
                        "class": cls_name,
                        "bbox": list(map(float, box.xyxy[0]))
                    })
            
            # 3. Cluster Overlapping Bounding Boxes
            table_clusters = cluster_elements(detections, "table", iou_thresh=0.25)
            annotated_img = cv_img.copy()
            
            # 4. Crop & Extract
            for table_count, cluster in enumerate(table_clusters, start=1):
                # Draw the merged bounding box
                x1, y1, x2, y2 = map(int, cluster["bbox"])
                cv2.rectangle(annotated_img, (x1, y1), (x2, y2), (0, 255, 0), 3)
                cv2.putText(annotated_img, "Table", (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
                
                # Apply Masked + Padded Crop
                crop_img = masked_crop_padded(cv_img, cluster["bbox"], cluster["members"], pad_pct=CROP_PADDING_PCT)
                if crop_img is None: continue

                crop_name = f"{base_name}_page{page_num}_table{table_count}.png"
                crop_path = os.path.join(DIRS["cropped"], crop_name)
                cv2.imwrite(crop_path, crop_img)
                
                # Extract JSON
                json_path = os.path.join(DIRS["json"], crop_name.replace(".png", ".json"))
                success = extract_table_json_with_gemini(crop_path, json_path)
                if success:
                    print(f"   ✅ Extracted table {table_count} on page {page_num}")
            
            if table_clusters:
                cv2.imwrite(os.path.join(DIRS["annotated"], img_name), annotated_img)

if __name__ == "__main__":
    main()

