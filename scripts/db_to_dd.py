import pandas as pd
import json
import os
import google.generativeai as genai

# --- CONFIGURATION ---
INPUT_CSV = "sample_dataset.csv"
OUTPUT_JSON = "inferred_data_dictionary.json"

# Set your API Key
os.environ["GEMINI_API_KEY"] = "AIzaSyDsNJ2kkcoQn8dW2P99e3cmT6j5jglmk5g"  # Replace or load from env
genai.configure(api_key=os.environ["GEMINI_API_KEY"])
vlm_model = genai.GenerativeModel("gemini-2.5-flash")

def profile_dataframe(df):
    """Uses Pandas to extract hard facts about the dataset."""
    profile = []
    
    for col in df.columns:
        # Get basic stats
        dtype = str(df[col].dtype)
        non_null = int(df[col].notnull().sum())
        total_rows = len(df)
        
        # Get up to 3 unique sample values to give the LLM context
        samples = df[col].dropna().unique().tolist()[:3]
        
        profile.append({
            "column_name": col,
            "inferred_type_pandas": dtype,
            "nullability": "Nullable" if non_null < total_rows else "Required",
            "samples": samples
        })
        
    return profile

def generate_semantic_dictionary(raw_profile):
    """Uses Gemini to guess the business meaning of the columns."""
    prompt = """
    You are an expert US Healthcare Data Analyst. 
    I am going to give you a raw data profile from a new client's database.
    
    For each column, provide:
    1. A human-readable 'business_name' (e.g., 'SRC_DX_CODE' -> 'Diagnosis Code')
    2. A detailed 'description' of what this data represents in US Healthcare.
    3. Any observed 'formatting_rules' based on the samples (e.g., 'YYYYMMDD', 'Alpha-numeric', etc.)
    
    Return the result as a STRICT JSON array of objects. Do not use markdown blocks like ```json.
    
    RAW PROFILE:
    {json.dumps(raw_profile, indent=2)}
    """
    
    print("   -> Asking Gemini to infer business logic...")
    try:
        response = vlm_model.generate_content(prompt)
        
        raw_text = response.text.strip()
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:-3].strip()
            
        semantic_data = json.loads(raw_text)
        return semantic_data
    except Exception as e:
        print(f"❌ Gemini Inference Failed: {e}")
        return None

def main():
    print("=== APPROACH 3: DB to DATA DICTIONARY ===")
    
    if not os.path.exists(INPUT_CSV):
        print(f"❌ Could not find {INPUT_CSV}")
        return
        
    # 1. Load Data
    print(f"📄 Loading {INPUT_CSV}...")
    df = pd.read_csv(INPUT_CSV)
    
    # 2. Programmatic Profiling (The Hard Facts)
    print("   -> Profiling data types and samples via Pandas...")
    raw_profile = profile_dataframe(df)
    
    # 3. LLM Semantic Inference (The Business Logic)
    enriched_dd = generate_semantic_dictionary(raw_profile)
    
    if not enriched_dd:
        return
        
    # 4. Merge Pandas Facts with Gemini Logic
    final_dictionary = []
    for i, col_data in enumerate(raw_profile):
        # Match the LLM output with the Pandas output
        llm_data = enriched_dd[i] if i < len(enriched_dd) else {}
        
        final_dictionary.append({
            "original_column": col_data["column_name"],
            "business_name": llm_data.get("business_name", "Unknown"),
            "data_type": col_data["inferred_type_pandas"],
            "required": col_data["nullability"],
            "description": llm_data.get("description", "No description generated"),
            "formatting_rules": llm_data.get("formatting_rules", ""),
            "sample_values": col_data["samples"]
        })
        
    # 5. Save the result
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(final_dictionary, f, indent=4)
        
    print(f"\n✅ Success! Data Dictionary generated and saved to {OUTPUT_JSON}")
    print("\nPreview of inferred definitions:")
    for col in final_dictionary[:3]:
        print(f"  - {col['original_column']} ➡️  {col['business_name']} ({col['description']})")

if __name__ == "__main__":
    main()