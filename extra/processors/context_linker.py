import numpy as np
import re

class BoundedContextLinkerEngine:
    """
    PHASE 2: STANDALONE INTELLECTUAL LAYER.
    Reads a structured, coordinate-rich intermediate JSON layout payload 
    and binds paragraph blocks using Local Bounded Term-Frequency Profiles.
    """
    def __init__(self, raw_layout_blueprint):
        self.blueprint = raw_layout_blueprint
        self.metrics = raw_layout_blueprint.get("calibrated_metrics", {"avg_line_height": 10.0})
        self.tables = raw_layout_blueprint.get("extracted_tables", [])
        self.paragraphs = raw_layout_blueprint.get("extracted_paragraphs", [])

    def execute_strategy_1_linking(self):
        print(f"🧠 Context Linker running Strategy 1 on schema matrix blocks...")
        
        # Reset assignment flags across the interim payload array entries
        for p in self.paragraphs:
            p["assigned"] = False

        for idx, t in enumerate(self.tables):
            t["intro_text"] = None
            t["footer_notes"] = None
            
            prev_t = self.tables[idx - 1] if idx > 0 else None
            next_t = self.tables[idx + 1] if idx < len(self.tables) - 1 else None
            
            # --- STEP 1: CONTEXT ENVELOPE ISOLATION ---
            envelope_paras = []
            for p in self.paragraphs:
                if p["assigned"]: continue
                if prev_t:
                    if p["page"] < prev_t["last_page"]: continue
                    if p["page"] == prev_t["last_page"] and p["top_y"] < prev_t["bottom_y"]: continue
                if next_t:
                    if p["page"] > next_t["page"]: continue
                    if p["page"] == next_t["page"] and p["bottom_y"] > next_t["top_y"]: continue
                envelope_paras.append(p)
                
            if not envelope_paras: continue
                
            # --- STEP 2: TABLE CELL TOKEN HARVESTING ---
            table_tokens = []
            for row in t["data_matrix"]:
                for cell in row:
                    tokens = re.findall(r'\b\w{2,}\b', str(cell).lower())
                    table_tokens.extend(tokens)
                    
            table_profile = {}
            for token in table_tokens:
                table_profile[token] = table_profile.get(token, 0) + 1
                
            if not table_profile: continue
                
            # Separate candidates into preceding (pre) and succeeding (post) blocks
            pre_candidates = []
            post_candidates = []
            for p in envelope_paras:
                if p["page"] < t["page"] or (p["page"] == t["page"] and p["bottom_y"] <= t["top_y"]):
                    pre_candidates.append(p)
                elif p["page"] > t["last_page"] or (p["page"] == t["last_page"] and p["top_y"] >= t["bottom_y"]):
                    post_candidates.append(p)

            # --- STEP 3: COSINE SIMILARITY MATH ---
            def compute_similarity(para_text, t_profile):
                p_tokens = re.findall(r'\b\w{2,}\b', para_text.lower())
                if not p_tokens: return 0.0
                p_profile = {}
                for token in p_tokens:
                    p_profile[token] = p_profile.get(token, 0) + 1
                    
                intersect_tokens = set(t_profile.keys()).intersection(set(p_profile.keys()))
                if not intersect_tokens: return 0.0
                    
                dot_product = sum(t_profile[tok] * p_profile[tok] for tok in intersect_tokens)
                norm_t = np.sqrt(sum(val ** 2 for val in t_profile.values()))
                norm_p = np.sqrt(sum(val ** 2 for val in p_profile.values()))
                return dot_product / (norm_t * norm_p) if (norm_t * norm_p) > 0 else 0.0

            # --- STEP 4: STATEFUL SEGMENT MATCHING ---
            best_pre_para, max_pre_score = None, -1.0
            for p in pre_candidates:
                score = compute_similarity(p["text"], table_profile)
                if score > max_pre_score:
                    max_pre_score = score
                    best_pre_para = p
                    
            # Proximity fallback rule if no exact cell vocabulary overlap is triggered
            if max_pre_score == 0.0 and pre_candidates:
                same_page_pre = [p for p in pre_candidates if p["page"] == t["page"]]
                if same_page_pre:
                    same_page_pre.sort(key=lambda x: t["top_y"] - x["bottom_y"])
                    if t["top_y"] - same_page_pre[0]["bottom_y"] < t.get("avg_line_height", 12.0) * 4:
                        best_pre_para = same_page_pre[0]
                        max_pre_score = 0.01

            if best_pre_para:
                t["intro_text"] = best_pre_para["text"]
                best_pre_para["assigned"] = True # 💡 Stateful Consume-and-Remove popping gate

            best_post_para, max_post_score = None, -1.0
            for p in post_candidates:
                score = compute_similarity(p["text"], table_profile)
                if p["text"].strip().lower().startswith(("note", "value", "*", "see", "valid")):
                    score += 0.25 # Semantic tracking weight boost
                if score > max_post_score:
                    max_post_score = score
                    best_post_para = p
                    
            if max_post_score == 0.0 and post_candidates:
                same_page_post = [p for p in post_candidates if p["page"] == t["last_page"]]
                if same_page_post:
                    same_page_post.sort(key=lambda x: x["top_y"] - t["bottom_y"])
                    if same_page_post[0]["top_y"] - t["bottom_y"] < t.get("avg_line_height", 12.0) * 4:
                        best_post_para = same_page_post[0]
                        max_post_score = 0.01

            if best_post_para:
                t["footer_notes"] = best_post_para["text"]
                best_post_para["assigned"] = True

        # Return a finalized payload optimized for consumption
        return {
            "document_id": self.blueprint.get("document_id"),
            "extracted_tables": [
                {
                    "table_id": t["table_id"],
                    "pages_spanned": t["pages_spanned"],
                    "intro_text": t["intro_text"],
                    "data_matrix": t["data_matrix"],
                    "footer_notes": t["footer_notes"]
                } for t in self.tables
            ],
            "standalone_paragraphs": [
                {"page": p["page"], "text": p["text"]} for p in self.paragraphs if not p["assigned"]
            ]
        }