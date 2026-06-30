import re

class ContextAndReferenceResolver:
    def __init__(self, step3_data):
        """
        STAGES 4 & 5: Multi-Axis Context Linking & Entity-Reference Cross Resolution.
        Executes phrase-agnostic lookup binding and structural timeline pairing.
        """
        self.doc_id = step3_data.get("document_id")
        self.source_format = step3_data.get("source_format")
        self.total_pages = step3_data.get("total_pages")
        self.timeline_elements = step3_data.get("elements", [])

    def _extract_table_tokens(self, matrix):
        """Compiles a semantic vocabulary profile from table row headers and cell values."""
        tokens = set()
        if not matrix:
            return tokens
        for row in matrix:
            for cell in row:
                cell_str = str(cell).strip()
                # Extract alphanumeric identifiers (e.g., 'ME001', 'CUR_CLM_UNIQ_ID')
                words = re.findall(r'\b[a-zA-Z0-9_\-]{3,}\b', cell_str)
                for w in words:
                    tokens.add(w.upper())
        return tokens

    def _score_and_bind_context(self):
        """
        STAGE 4: Multi-Axis Heuristic Scoring.
        Determines whether timeline paragraphs belong to an upper table, a lower table, 
        or stand alone globally.
        """
        processed_blocks = []
        
        # Isolate indices of tables in the timeline
        table_indices = [i for i, e in enumerate(self.timeline_elements) if e["type"] == "table"]
        
        # Pre-calculate token vocabularies for all tables to resolve axis 3
        table_vocabularies = {}
        for idx in table_indices:
            table_vocabularies[idx] = self._extract_table_tokens(self.timeline_elements[idx]["raw_matrix"])

        # Loop through timeline intervals between tables
        for loop_idx, t_idx in enumerate(table_indices):
            # Define boundaries of the chronological envelope
            prev_t_idx = table_indices[loop_idx - 1] if loop_idx > 0 else -1
            
            # Extract paragraphs sitting between the previous table and current table
            intervening_paras = [
                self.timeline_elements[i] for i in range(prev_t_idx + 1, t_idx)
                if self.timeline_elements[i]["type"] == "paragraph"
            ]
            
            intro_context = []
            
            for para in intervening_paras:
                text = para["text"]
                text_lower = text.lower()
                
                # AXIS 1: Structural Trait Signals
                is_intro_signal = text_lower.startswith(('appendix', 'table', 'section', 'chapter', 'file layout')) or text.endswith(':')
                is_footer_signal = text_lower.startswith(('note:', 'example:', 'default:', 'values:', '*')) or 'padded with spaces' in text_lower
                
                # AXIS 3: Token Overlap Matrix
                para_words = set(w.upper() for w in re.findall(r'\b[a-zA-Z0-9_\-]{3,}\b', text))
                overlap_current = len(para_words.intersection(table_vocabularies[t_idx]))
                overlap_prev = len(para_words.intersection(table_vocabularies[prev_t_idx])) if prev_t_idx != -1 else 0
                
                # COMBINED HEURISTIC EVALUATION GATE
                if is_intro_signal or (overlap_current > overlap_prev and not is_footer_signal):
                    # Snap down to the current incoming table as introductory metadata
                    intro_context.append(para["text"])
                    para["_assigned_to_table"] = True
                elif prev_t_idx != -1 and (is_footer_signal or (overlap_prev > overlap_current)):
                    # Snap up to the preceding table as a clarifying footer note
                    for block in processed_blocks:
                        if block["element_id"] == f"context_group_{loop_idx - 1}":
                            block["footer_context"].append(para["text"])
                            para["_assigned_to_table"] = True
                            break

            # Pack the calibrated schema cluster node
            processed_blocks.append({
                "element_id": f"context_group_{loop_idx}",
                "type": "schema_cluster",
                "pages_spanned": self.timeline_elements[t_idx]["pages_spanned"],
                "introductory_context": intro_context,
                "table": {
                    "headers": self.timeline_elements[t_idx]["raw_matrix"][0] if self.timeline_elements[t_idx]["raw_matrix"] else [],
                    "matrix": self.timeline_elements[t_idx]["raw_matrix"][1:] if len(self.timeline_elements[t_idx]["raw_matrix"]) > 1 else []
                },
                "footer_context": []
            })

        # Collect any remaining paragraphs with low structural weight as standalone metadata
        standalone_metadata = [
            e["text"] for e in self.timeline_elements
            if e["type"] == "paragraph" and not e.get("_assigned_to_table", False)
        ]

        return processed_blocks, standalone_metadata

    def resolve_references_and_graph(self, schema_clusters, standalone_metadata):
        """
        STAGE 5: Entity Graph Discovery Index.
        Extracts known data-element identifiers and resolves relational foreign-key references.
        """
        # 1. BUILD MASTER KNOWN-ENTITY DISCOVERY INDEX
        known_entities = set()
        
        for cluster in schema_clusters:
            # Index structural table/appendix headers from introductory context strings
            for intro in cluster["introductory_context"]:
                labels = re.findall(r'\b(?:Table|Appendix|Layout)\s+([a-zA-Z0-9_\-]+)\b', intro, re.IGNORECASE)
                for label in labels:
                    known_entities.add(label.upper())
                    
            # Index primary field codes directly from column index 0 (e.g., 'ME001', 'CUR_CLM_UNIQ_ID')
            for row in cluster["table"]["matrix"]:
                if row and row[0]:
                    known_entities.add(str(row[0]).strip().upper())

        # 2. RUN PHRASE-AGNOSTIC CROSS MATCHING LOOKUPS
        final_clusters = []
        for cluster in schema_clusters:
            updated_matrix = []
            
            for row in cluster["table"]["matrix"]:
                if not row:
                    continue
                row_extended = {
                    "cells": row,
                    "has_external_reference": False,
                    "reference_targets": []
                }
                
                # Inspect cell values across the description/comment column spaces
                row_text_combined = " ".join(str(cell) for cell in row).upper()
                tokens = re.findall(r'\b[a-zA-Z0-9_\-]{3,}\b', row_text_combined)
                
                for token in tokens:
                    # Guard Check: Prevent a field from cross-referencing its own row index label
                    if token in known_entities and token != str(row[0]).strip().upper():
                        row_extended["has_external_reference"] = True
                        if token not in row_extended["reference_targets"]:
                            row_extended["reference_targets"].append(token)
                            
                updated_matrix.append(row_extended)
                
            cluster["table"]["matrix"] = updated_matrix
            final_clusters.append(cluster)

        return {
            "document_id": self.doc_id,
            "source_format": self.source_format,
            "total_pages": self.total_pages,
            "global_metadata": standalone_metadata,
            "schema_clusters": final_clusters
        }

    def process(self):
        print(f"🧠 Parsing intellectual layout layers for: {self.doc_id}")
        schema_clusters, standalone_metadata = self._score_and_bind_context()
        final_er_blueprint = self.resolve_references_and_graph(schema_clusters, standalone_metadata)
        return final_er_blueprint