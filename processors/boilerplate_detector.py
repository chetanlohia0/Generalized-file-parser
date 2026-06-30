import re

class BoilerplateDetector:
    def __init__(self, step1_data):
        """
        STAGE 2: Standardized Boilerplate & System Noise Isolation.
        Filters out structural layout noise by executing a sliding neighbor-page
        window validation track (checking n-1 and n+1 page blocks).
        """
        self.blueprint = step1_data
        self.pages = step1_data.get("pages", [])

    def _normalize_text(self, text):
        """
        Applies digit masking and collapses spacing to standardize 
        structural text streams cleanly.
        """
        text_clean = text.lower().strip()
        # Apply digit masking to capture variable sequential labels (e.g., 'Page 1' vs 'Page 2')
        text_clean = re.sub(r'\d+', '#', text_clean)
        # Collapse multiple spaces into a single space character
        return re.sub(r'\s+', ' ', text_clean)

    def detect_and_strip(self):
        # Step 1: Pre-calculate normalized text patterns for all pages to ensure fast execution
        page_text_registry = {}
        for page in self.pages:
            p_num = page["page_number"]
            page_text_registry[p_num] = []
            
            for elem in page["elements"]:
                if elem["type"] == "text_line":
                    norm = self._normalize_text(elem["text"])
                    page_text_registry[p_num].append({
                        "element_id": elem["element_id"],
                        "raw_text": elem["text"],
                        "norm_text": norm,
                        "ratio": elem["vertical_position_ratio"]
                    })

        boilerplate_ids = set()
        boilerplate_tracking = {}

        # Step 2: Run neighborhood validation sliding window pass
        for p_num in sorted(page_text_registry.keys()):
            # Define local window boundaries (Strictly look at page n-1 and page n+1)
            neighbors = []
            if p_num - 1 in page_text_registry:
                neighbors.append(p_num - 1)
            if p_num + 1 in page_text_registry:
                neighbors.append(p_num + 1)
                
            for elem in page_text_registry[p_num]:
                is_boilerplate = False
                
                # RULE 1: First, check if the exact normalized string pattern exists in neighbors
                for neighbor_p in neighbors:
                    for neighbor_elem in page_text_registry[neighbor_p]:
                        if elem["norm_text"] == neighbor_elem["norm_text"]:
                            
                            # RULE 2: If text matches, check the vertical coordinate position
                            if abs(elem["ratio"] - neighbor_elem["ratio"]) <= 0.03:
                                is_boilerplate = True
                                break
                    if is_boilerplate:
                        break
                        
                if is_boilerplate:
                    # Mark element ID to be stripped from the core data flow
                    boilerplate_ids.add(elem["element_id"])
                    
                    # Group by normalized text pattern and vertical bucket position
                    v_bucket = round(elem["ratio"], 2)
                    tracking_key = (elem["norm_text"], v_bucket)
                    
                    if tracking_key not in boilerplate_tracking:
                        boilerplate_tracking[tracking_key] = {
                            "representative_text": elem["raw_text"],
                            "vertical_position_ratio": v_bucket,
                            "pages": set()
                        }
                    # Save the page coordinate into our single unique text record
                    boilerplate_tracking[tracking_key]["pages"].add(p_num)

        # Step 3: Format the boilerplate reference data cleanly (saving text only once)
        boilerplate_list = []
        for key, data in boilerplate_tracking.items():
            boilerplate_list.append({
                "text": data["representative_text"],
                "vertical_position_ratio": data["vertical_position_ratio"],
                "pages": sorted(list(data["pages"])) # Standardized integer page array
            })
            
        # Sort output chronologically by vertical page position ratio
        boilerplate_list.sort(key=lambda x: x["vertical_position_ratio"])

        # Step 4: Construct the clean Silver Layer elements stream
        stripped_pages = []
        for page in self.pages:
            clean_elements = [
                elem for elem in page["elements"]
                if elem["element_id"] not in boilerplate_ids
            ]
            
            stripped_pages.append({
                "page_number": page["page_number"],
                "page_height": page["page_height"],
                "page_width": page["page_width"],
                "elements": clean_elements
            })

        stripped_blueprint = {
            "document_id": self.blueprint.get("document_id"),
            "source_format": self.blueprint.get("source_format"),
            "total_pages": self.blueprint.get("total_pages"),
            "pages": stripped_pages
        }

        print(f"🧹 [DE-NOISE] Cleaned boilerplate elements from the core stream.")
        return stripped_blueprint, boilerplate_list