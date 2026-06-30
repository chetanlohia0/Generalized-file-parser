import requests
import json
import os
import re

class LLMContextLinker:
    def __init__(self, step3_data):
        """
        STAGE 4: Local LLM Contiguous Boundary Identification Pass.
        Passes the entire continuous text envelope above and below each table matrix 
        directly to Qwen-2.5-3B to locate exact context split-points.
        """
        self.doc_id = step3_data.get("document_id")
        self.source_format = step3_data.get("source_format")
        self.total_pages = step3_data.get("total_pages")
        self.timeline_elements = step3_data.get("elements", [])
        self.ollama_url = "http://localhost:11434/api/generate"

    def _query_local_ollama(self, prompt):
        """Executes a direct network call to the local background Ollama endpoint service."""
        payload = {
            "model": "qwen2.5:3b",
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.0, # Complete determinism for tracking index strings
                "top_p": 0.1
            }
        }
        try:
            response = requests.post(self.ollama_url, json=payload, timeout=60)
            if response.status_code == 200:
                return response.json().get("response", "").strip()
            return "NONE"
        except Exception as e:
            print(f"    ⚠️  Ollama connection failed: {e}. Check if 'ollama serve' is running.")
            return "NONE"

    def _extract_valid_block_id(self, raw_response, valid_ids):
        """Isolates the target block ID string from any potential wrapper text filler."""
        matches = re.findall(r'\bglobal_block_\d+\b', raw_response)
        if matches and matches[0] in valid_ids:
            return matches[0]
        if "NONE" in raw_response.upper():
            return "NONE"
        return "NONE"

    def execute_linking(self):
        print(f"🧠 Local LLM Segment Pointer Pass engaged for: {self.doc_id}")
        
        # Isolate the index positions of all continuous table blocks
        table_indices = [i for i, e in enumerate(self.timeline_elements) if e["type"] == "table"]
        schema_clusters = []
        claimed_element_ids = set()

        for loop_idx, t_idx in enumerate(table_indices):
            # Compute chronological envelope boundaries back to prev table and forward to next table
            prev_t_idx = table_indices[loop_idx - 1] if loop_idx > 0 else -1
            next_t_idx = table_indices[loop_idx + 1] if loop_idx < len(table_indices) - 1 else len(self.timeline_elements)

            current_table = self.timeline_elements[t_idx]
            print(f"  🤖 Querying local 3B model for table block {loop_idx + 1}/{len(table_indices)}...")

            # Extract 100% of the raw preceding text lines between tables
            pre_candidates = [
                self.timeline_elements[i] for i in range(prev_t_idx + 1, t_idx)
                if self.timeline_elements[i]["type"] == "paragraph"
            ]
            
            # Extract 100% of the raw succeeding text lines between tables
            post_candidates = [
                self.timeline_elements[i] for i in range(t_idx + 1, next_t_idx)
                if self.timeline_elements[i]["type"] == "paragraph"
            ]

            intro_context = []
            footer_context = []

            # --- PASS A: DETECT STARTING BOUNDARY FOR INTRODUCTORY CONTEXT ---
            if pre_candidates:
                pre_summary = "\n".join([f"- ID: {p['element_id']} | Text: \"{p['text']}\"" for p in pre_candidates])
                valid_pre_ids = [p["element_id"] for p in pre_candidates]
                
                intro_prompt = f"""You are a precise data router for automated database ingestion engines.
Analyze the following chronological sequence of text blocks located immediately ABOVE the Target Table Schema.

[TARGET TABLE SCHEMA HEADERS]:
{current_table['raw_matrix'][0]}

[AVAILABLE TEXT BLOCKS]:
{pre_summary}

TASK:
Identify the exact element ID where the continuous introductory text, titles, naming conventions, or data layouts specific to this Target Table begin.
Context is strictly contiguous. Everything from that starting element ID down to the table is related.
If all available blocks are global metadata (like a Table of Contents or general overview), return "NONE".

REQUIREMENT:
Return ONLY the raw ID string (e.g., global_block_5). Do not write conversational filler or markdown brackets.
"""
                raw_resp = self._query_local_ollama(intro_prompt)
                split_point_id = self._extract_valid_block_id(raw_resp, valid_pre_ids)
                
                if split_point_id != "NONE":
                    # Because context is contiguous, capture everything from that split point down to the table
                    capture_flag = False
                    for p in pre_candidates:
                        if p["element_id"] == split_point_id:
                            capture_flag = True
                        if capture_flag:
                            intro_context.append(p["text"])
                            claimed_element_ids.add(p["element_id"])

            # --- PASS B: DETECT ENDING BOUNDARY FOR FOOTER NOTES ---
            if post_candidates:
                post_summary = "\n".join([f"- ID: {p['element_id']} | Text: \"{p['text']}\"" for p in post_candidates])
                valid_post_ids = [p["element_id"] for p in post_candidates]
                
                footer_prompt = f"""You are a precise data layout router. 
Analyze the following chronological sequence of text blocks located immediately BELOW the Target Table Schema.

[TARGET TABLE SCHEMA HEADERS]:
{current_table['raw_matrix'][0]}

[AVAILABLE TEXT BLOCKS]:
{post_summary}

TASK:
Identify the exact element ID where the validation codes, footnote definitions, or override parameters specific to this Target Table end.
Context is strictly contiguous. Everything from the table down to that ending element ID is related.
If none of these blocks are footers for this table, return "NONE".

REQUIREMENT:
Return ONLY the raw ID string (e.g., global_block_12). Do not write conversational filler or markdown brackets.
"""
                raw_resp = self._query_local_ollama(footer_prompt)
                split_point_id = self._extract_valid_block_id(raw_resp, valid_post_ids)
                
                if split_point_id != "NONE":
                    # Capture everything from the table down to that ending element ID boundary
                    for p in post_candidates:
                        footer_context.append(p["text"])
                        claimed_element_ids.add(p["element_id"])
                        if p["element_id"] == split_point_id:
                            break

            # Pack the consolidated cluster payload block
            schema_clusters.append({
                "element_id": f"context_group_{loop_idx}",
                "type": "schema_cluster",
                "pages_spanned": current_table["pages_spanned"],
                "introductory_context": intro_context,
                "table": {
                    "headers": current_table["raw_matrix"][0] if current_table["raw_matrix"] else [],
                    "matrix": current_table["raw_matrix"][1:] if len(current_table["raw_matrix"]) > 1 else []
                },
                "footer_context": footer_context
            })

        # Gather remaining unclaimed elements into the global standalone bucket array
        standalone_metadata = [
            e["text"] for e in self.timeline_elements
            if e["type"] == "paragraph" and e["element_id"] not in claimed_element_ids
        ]

        return {
            "document_id": self.doc_id,
            "source_format": self.source_format,
            "total_pages": self.total_pages,
            "global_metadata": standalone_metadata,
            "schema_clusters": schema_clusters
        }