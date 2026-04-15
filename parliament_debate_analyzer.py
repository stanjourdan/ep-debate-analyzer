"""
Plenary Debate Analysis
Extracts, translates, and analyzes European Parliament plenary debates.

Workflow:
1. EXTRACTION: Download and parse europarl XML debate files
2. MATCHING: Cross-reference speakers with MEP database for full names, groups, countries
3. TRANSLATION: Selective translation of non-English speeches to English
4. EXPORT: Generate Markdown transcripts with all processed speeches
5. ANALYSIS: Map-Reduce pattern for political group analysis and cross-group synthesis

External Dependencies:
- Ollama server running on localhost:11434 with models:
  * llama3.2:3b (translation)
  * qwen2.5:3b (synthesis/group analysis)
  * mistral:7b-instruct-v0.3-q4_K_M (cross-group analysis)
- MEP database XML at ~/Python/resources/meps_all.xml

"""

import os
import re
import requests
from lxml import etree
import time
from datetime import datetime

# ==========================================
# UTILITY FUNCTIONS
# ==========================================

def download_xml(xml_url):
    try:
        response = requests.get(xml_url)
        response.raise_for_status()
        return response.content
    except requests.exceptions.RequestException as e:
        print(f"❌ Download failure: {e}")
        return None

def parse_xml(xml_content):
    try:
        return etree.fromstring(xml_content)
    except Exception as e:
        print(f"❌ Parsing failure: {e}")
        return None

def load_meps_database(filepath):
    print(f"📂 Loading {filepath}...")
    try:
        with open(filepath, 'rb') as file:
            tree = etree.parse(file)
        meps_db = {}
        for mep in tree.xpath('//mep'):
            mepid = mep.findtext('id')
            if mepid:
                meps_db[mepid] = {
                    'FullName': mep.findtext('fullName'),
                    'politicalGroup': mep.findtext('politicalGroup'),
                    'country': mep.findtext('country')
                }
        print(f"✅ {len(meps_db)} MEPs loaded.")
        return meps_db
    except Exception as e:
        print(f"❌ Error loading database: {e}")
        return {}

def translate_to_english(text, lang_source, model_trans):
    """
    Translate text to English using Ollama LLM inference.
    
    Args:
        text (str): Text to translate
        lang_source (str): Source language code (e.g., 'FR', 'DE', 'IT')
        model_trans (str): Ollama model name for translation
    
    Returns:
        str: Translated English text, or original text if translation failed
    """
    system_prompt = 'You are a professional translator. Your task is to translate any text into ENGLISH. Never output any other language than English.No introductions, no explanations, no "Here is the translation"' 
    user_prompt = f"Translate the following text from {lang_source} to English.\nText: {text}"
    url = "http://localhost:11434/api/generate"
    payload = {
        "model": model_trans, 
        "system": system_prompt,
        "prompt": user_prompt, 
        "stream": False,
        "options": {
            "temperature": 0.0
        }
    }
    try:
        response = requests.post(url, json=payload, timeout=240)
        response.raise_for_status()
        return response.json().get("response", "").strip()
    except Exception as e:
        print(f"❌ Ollama error: {e}")
        return text  # Returns original text if error occurs

def generate_summary(system_prompt, user_prompt, model):
    url = "http://localhost:11434/api/generate"

    payload = {
        "model": model,
        "system": system_prompt,  # 🧠 The strict rules
        "prompt": user_prompt,          # 📄 The text to analyze
        "stream": False,
        "options": {
            "num_ctx": 12000 if len(user_prompt) > 15000 else 6192,  # Release the context window
            #"num_gpu": 50,        # disabled for now, let Ollama decide
            "temperature": 0.15    # low treshold for more stable syntheses
    }}
    try:
        # Longer timeout because synthesis analyzes large amounts of text
        response = requests.post(url, json=payload, timeout=None) 
        response.raise_for_status()
        return response.json().get("response", "").strip()
    except Exception as e:
        print(f"❌ Ollama error (synthesis): {e}")
        return f"Error generating summary: {e}"

# ==========================================
# MAIN PIPELINE
# ==========================================
def main():
    # --- General configuration ---
    raw_urls = input("""📝 Provide URLs of europarl XML files (separated by spaces or comma): """)
    xml_urls = [url.strip() for url in raw_urls.replace(',', ' ').split() if url.strip()]
    # Example of expected URL: https://www.europarl.europa.eu/doceo/document/CRE-10-2026-02-12-ITM-009_EN.xml
    policy_priorities = input("""What is the policy focus? """)
    
    # Configuration
    base_path = os.path.dirname(os.path.abspath(__file__))
    meps_path = os.path.join(base_path, 'meps_all.xml')
    ollama_host = "http://localhost:11434"
    
    # Verify MEP database exists
    if not os.path.exists(meps_path):
        print(f"❌ ERROR: MEP database not found at {meps_path}")
        print(f"   Please download from: https://www.europarl.europa.eu/meps/en/xml")
        print(f"   Or update meps_path in the script to the correct location.")
        return
    
    model_trans = "llama3.2:3b"  # TODO: Make configurable
    model_synthesis = "qwen2.5:3b"  # TODO: Make configurable
    model_reduce = "mistral:7b-instruct-v0.3-q4_K_M"  # TODO: Make configurable

    meps_db = load_meps_database(meps_path)
    
    for i, xml_url in enumerate(xml_urls, 1):
        print(f"\n{'='*60}")
        print(f"🚀 DEBATE [{i}/{len(xml_urls)}]: {xml_url}")
        print(f"{'='*60}")

        # --- Phase 1: Extraction ---
        print("\n--- PHASE 1: EXTRACTION ---")
        xml_content = download_xml(xml_url)
        if not xml_content: continue
        xml_tree = parse_xml(xml_content)
        
        # Retrieve raw speech blocks
        all_speechs_xml = xml_tree.xpath(".//*[local-name()='INTERVENTION']")
        
        # --- STEP 1: Detect Written Statements (Rule 178) marker ---
        in_written_statements = False
        verbal_interventions = []
        written_statements_data = []
        
        for intervention in all_speechs_xml:
            # Check if this intervention contains the written statements marker
            emphas_nodes = intervention.xpath(".//EMPHAS[@NAME='I']")
            is_written_marker = any(
                node.text and "Written Statements (Rule 178)" in node.text 
                for node in emphas_nodes
            )
            
            if is_written_marker:
                in_written_statements = True
                continue  # Skip the marker intervention itself
            
            if in_written_statements:
                written_statements_data.append(intervention)
            else:
                verbal_interventions.append(intervention)
        
        # Use only verbal interventions for processing
        all_speechs_xml = verbal_interventions
        
        # Create debate metadata dictionary
        title_node = xml_tree.find("TL-CHAP[@VL='EN']")
        debate_title = title_node.text if title_node is not None else "Untitled_Debate"
        date_match = re.search(r'CRE-\d+-(20\d{2}-\d{2}-\d{2})', xml_url)   # Extract date from URL (e.g., 2026-03-10)
        debate_date = date_match.group(1) if date_match else "Unknown-Date"
        safe_title = re.sub(r'[^A-Za-z0-9 ]+', '', debate_title)[:25].strip().replace(' ', '_')
        
        debate_dict = {
            "debate_title": debate_title,
            "debate_date": debate_date,
            "safe_title" : safe_title
        }

        # --- Phase 2: Matching with MEP database ---
        print("\n--- PHASE 2: MATCHING ---")
        full_speechs_dict = []
        
        for bloc in all_speechs_xml:
            speaker_nodes = bloc.xpath(".//*[local-name()='ORATEUR']")
            if not speaker_nodes: continue
            speaker_node = speaker_nodes[0]
            
            mepid = speaker_node.get("MEPID")
            lang = speaker_node.get("LG", "EN")
            
            raw_role = speaker_node.get("SPEAKER_TYPE", "").strip()
            role = "Group spokesperson" if raw_role.lower() == "au nom du groupe" else raw_role
            
            # Match with MEP database
            if mepid and mepid in meps_db:
                fullname = meps_db[mepid]["FullName"]
                politicalgroup = meps_db[mepid]["politicalGroup"]
                country = meps_db[mepid]["country"]
            else:
                fullname = speaker_node.get("LIB", "Unknown")
                politicalgroup = speaker_node.get("PP", "Unknown")
                country = "n/a"
                
            # Extract and clean text content
            paras = bloc.xpath(".//PARA")
            cleaned_paras = []
            
            for p in paras:
                text_parts = []
                for node in p.xpath("node()"):
                    if isinstance(node, etree._Element) and node.tag == "EMPHAS" and node.get("NAME") == "I":
                        continue
                    if isinstance(node, etree._Element):
                        text_parts.append("".join(node.itertext()))
                    else:
                        text_parts.append(str(node))
                
                cleaned_paras.append("".join(text_parts))

            text_content = " ".join(cleaned_paras).strip()
            
            text_content = re.sub(r'^[\s\.\–\-]+', '', text_content).strip()
            
            if fullname and text_content:
                full_speechs_dict.append({
                    "Fullname": fullname,
                    "politicalgroup": politicalgroup,
                    "country": country,
                    "lang": lang,
                    "role": role,
                    "text": text_content
                })
        
        # --- Extract Written Statements authors ---
        written_mep_authors = set()
        for bloc in written_statements_data:
            speaker_nodes = bloc.xpath(".//*[local-name()='ORATEUR']")
            if speaker_nodes:
                speaker_node = speaker_nodes[0]
                mepid = speaker_node.get("MEPID")
                
                if mepid and mepid in meps_db:
                    written_mep_authors.add(meps_db[mepid]["FullName"])
                else:
                    fullname_alt = speaker_node.get("LIB", "Unknown")
                    if fullname_alt and fullname_alt != "Unknown":
                        written_mep_authors.add(fullname_alt)
        
        written_mep_authors = sorted(list(written_mep_authors))
        written_statements_count = len(written_statements_data)
        
        start_time = time.time()

        # --- Phase 3: Selective translation ---
        print(f"\n--- PHASE 3: SELECTIVE TRANSLATION ({len(full_speechs_dict)} speeches) ---")
        for i, speech in enumerate(full_speechs_dict):
            # Translate all non-English speeches
            if speech["lang"].upper() != "EN":
                print(f"[{i+1}/{len(full_speechs_dict)}] 🌐 Translating {speech['Fullname']} ({speech['lang']})...")
                speech["text_translated"] = translate_to_english(speech["text"], speech["lang"], model_trans)
            else:
                speech["text_translated"] = speech["text"]
                print(f"[{i+1}/{len(full_speechs_dict)}] ✅ {speech['Fullname']} already in English.")
        total_duration = time.time() - start_time
        print(f"⏱️ Total time for translation: {total_duration:.2f} seconds.")

        # --- Phase 4: Export to Markdown ---
        print("\n--- PHASE 4: EXPORT MARKDOWN ---")

        debate_folder_name = f"{debate_dict['debate_date']}_{safe_title}"
        outputdir = os.path.join(base_path, 'output', debate_folder_name)
        os.makedirs(outputdir, exist_ok=True)

        base_filename = f"{debate_dict['debate_date']}_{safe_title}"
        
        # 1. Initial file paths
        filepath_transcript = os.path.join(outputdir, f"TRANSCRIPT_{base_filename}.md")
        filepath_summary = os.path.join(outputdir, f"SUMMARY_{base_filename}.md")

        # 2. Safe versioning (avoid overwriting existing files)
        if os.path.exists(filepath_transcript):
            v = 1
            while True:
                candidate_t = os.path.join(outputdir, f"TRANSCRIPT_{base_filename}_v{v}.md")
                candidate_s = os.path.join(outputdir, f"SUMMARY_{base_filename}_v{v}.md")
                if not os.path.exists(candidate_t):
                    filepath_transcript = candidate_t
                    filepath_summary = candidate_s
                    break
                v += 1
                if v > 100: break  # Safety limit to prevent infinite loop
        
        # 3. Write to files
        with open(filepath_transcript, 'w', encoding='utf-8') as f:
            # En-tête du fichier MD
            f.write(f"# {debate_dict['debate_title']}\n\n")
            f.write(f"**Date :** {debate_dict['debate_date']}\n")
            f.write(f"Translated by {model_trans}\n")
            f.write("---\n\n")
            
            # Corps du fichier (les discours)
            for speech in full_speechs_dict:
                f.write(f"### {speech['Fullname']} ({speech['politicalgroup']}, {speech['country']})\n")
                if speech['role']:
                    f.write(f"- **Role :** {speech['role']}\n")
                f.write("\n")
                f.write(f"> {speech['text_translated']}\n\n")
                if speech['lang'] != "EN":
                    f.write(f"(Original language: {speech['lang']})\n\n")
                f.write("---\n\n")
            
            # --- Add Written Statements footer ---
            if written_statements_count > 0:
                html_url = xml_url.replace('.xml', '.html')
                authors_text = ", ".join(written_mep_authors)
                f.write("---\n\n")
                f.write(f"**Note:** {written_statements_count} written statement(s) submitted by {authors_text}. "
                        f"[Read the statements here]({html_url})\n")

        print(f"💾 Saving transcript: {os.path.basename(filepath_transcript)}")
      
        # Read the markdown file we just created for use as context
        with open(filepath_transcript, 'r', encoding='utf-8') as f:
            markdown_content = f.read()
    
        # --- Analysis Phase: Speech summaries ---

        print(f"\n⏳ Generating MEP speech summaries (mapping with {model_synthesis})")
        # Step 2A (Map): Extract context and loop through political groups
        #contexte_intro = ""
        for s in full_speechs_dict[:3]:
            role_str = f" ({s['role']})" if s['role'] else ""
            #contexte_intro += f"{s['Fullname']}{role_str}: {s['text_translated']}\n\n"

        groups_to_analyze = ["EPP", "S&D", "Renew", "Greens/EFA", "ECR", "LEFT", "Non-attached"]
        mini_summaries = ""
        total_time_v2a = 0

        print("  🔍 Generating quick digest per political group")
        for group in groups_to_analyze:
            group_speechs = ""
            for s in full_speechs_dict:
                if s.get('politicalgroup') and group.lower() in s['politicalgroup'].lower():
                    group_speechs += f"{s['Fullname']}: {s['text_translated']}\n\n"
            
            if not group_speechs.strip():
                continue
            
            enriched_context = f"{group_speechs}"
            system_prompt = f"You are a neutral EU political analyst."""

            user_prompt_v1 = f"""Task: List MEPs from {group} who spoke, summarize their core arguments and unique perspective.
            ==START OF TEXT TO ANALYZE==
            {group_speechs}
            ==END OF TEXT TO ANALYZE==
            Constraints:
            - Use a maximum of 1 to 3 bullet points per MEP.
            - Limit yourself to one sentence per bullet point.
            - Put MEPs names in **bold**.
            - Output language: English."""
                        
            start_g = time.time()
            summary_g = generate_summary(system_prompt, user_prompt_v1, model_reduce)
            time_g = time.time() - start_g
            total_time_v2a += time_g
            
            mini_summaries += f"### {group}\n{summary_g}\n\n"

        # Step 2B (Reduce): Overall synthesis and cross-group analysis
        print("  🧠 Generating final overall analysis...")
        system_prompt = f"You are a senior political analyst focusing on parliamentary deliberations."
        prompt_v2 = f"""Task: Summarize the overall debate.\n 
        ==TEXT TO ANALYZE== 
        {mini_summaries} 
        ==END OF TEXT==
        Constraints:
        - If applicable, highlight MEPs who explicitly made references to {policy_priorities}. If none, skip this.
        - Put MEP names and key topics in **bold**
        - no conclusion needed       
        """

        start_v2b = time.time()
        final_cross_analysis = generate_summary(system_prompt, prompt_v2, model_synthesis)
        time_v2b = time.time() - start_v2b
        print(f"✅ Summary completed. (Map: {total_time_v2a:.2f}s | Reduce: {time_v2b:.2f}s)")

        # --- Export the summary file ---
        # =========================================================
        # FINAL FILE EXPORT
        # =========================================================
        print("\n💾 Saving the summary file...")
        current_time = datetime.now().strftime("%Y-%m-%d at %H:%M:%S")
        with open(filepath_summary, 'w', encoding='utf-8') as f:
            f.write(f"# Plenary debate summary : {debate_dict['debate_title']}\n\n")
            f.write(f"**Created by:** {model_synthesis} + {model_reduce} on {current_time} \n\n---\n\n")
            f.write(f"Policy focus: {policy_priorities}\n\n---\n\n")
                                   
            f.write("### 1. Overall synthesis\n")
            f.write(f"{final_cross_analysis}\n\n---\n\n")
            
            f.write("### 2. Detailed speeches per group\n")
            f.write(f"{mini_summaries}\n")
            
            # --- Add Written Statements footer ---
            if written_statements_count > 0:
                html_url = xml_url.replace('.xml', '.html')
                authors_text = ", ".join(written_mep_authors)
                f.write("---\n\n")
                f.write(f"**Note:** {written_statements_count} written statement(s) submitted by {authors_text}. "
                        f"[Read the statements here]({html_url})\n")

        print(f"\n🎉 SUCCESS ! The summary is saved here : {filepath_summary}")

if __name__ == "__main__":
    main()