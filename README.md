# Plenary Digest: European Parliament Debate Analysis

Extract, translate, and analyze European Parliament plenary debates from XML sources. This tool automatically downloads plenary sessions, extracts speeches, translates non-English content to English, and generates short summaries of each MEP speech. Ultimately it offers an overall synthesis (to be improved)

## Features

- **Automated Extraction**: Downloads and parses plenary debate XML from europarl.europa.eu
- **Dynamic Translation**: Translates non-English speeches to English using Ollama
- **MEP Database Integration**: Cross-references speakers with the MEP (Members of the European Parliament) database. NB: MEPs database only includes in office as of March 2026
- **Markdown Export**: Generates formatted transcripts of all MEPs interventions
- **Political Analysis**: Map-Reduce pattern for analyzing speeches by political group and overall debate synthesis
- **Versioning**: Safe file output with automatic versioning to prevent data loss

## Prerequisites

### System Requirements
- Python 3.7 or higher
- Ollama (local LLM inference server)

### Required Ollama Models
The pipeline requires these models running on your Ollama instance:
- `llama3.2:3b` - For speech translation
- `qwen2.5:3b` - For synthesis if each MEP speech
- `mistral:7b-instruct-v0.3-q4_K_M` - For detailed overall analysis

### MEP Database  

- The MEPs database conatains about 1,700 MEPs from the period 2014-2026, including their names, political groups, and countries.
- It is now automatically downloaded from this separate GitHub repository [stanjourdan/meps-dataset](https://github.com/stanjourdan/meps-dataset/blob/main/meps_all-2014-2026.xml) and cached locally.
- The script will always attempt to fetch the latest version and fall back to the cache if the download fails.

## Setup

### 1. Clone and Install Dependencies
```bash
git clone <repository-url>
cd plenary-digest
pip install -r requirements.txt
```

### 2. Configure Ollama
Ensure Ollama is running on `localhost:11434` (default):
```bash
ollama serve
```

In another terminal, pull required models:
```bash
ollama pull llama3.2:3b
ollama pull qwen2.5:3b
ollama pull mistral:7b-instruct-v0.3-q4_K_M
```

## Usage

Run the main script:
```bash
python parliament_debate_analyzer.py
```

The script will prompt you for:
1. **XML URLs**: Paste one or more europarl plenary debate XML URLs (separated by spaces or commas)
   - Example: `https://www.europarl.europa.eu/doceo/document/CRE-10-2026-03-10-ITM-003_EN.xml`
2. **Policy Focus**: Enter a policy area of interest (e.g., "economic policy", "climate change")

### Output

Generated files are saved in `output/<date>_<debate-title>/`:
- `TRANSCRIPT_<date>_<title>.md` - Full transcript with all speeches in English
- `SUMMARY_<date>_<title>.md` - Analysis summary including:
  - Overall synthesis
  - Detailed summaries per political group
  - Relevance to policy focus (if applicable)

## Known Limitations

1. **Hardcoded Paths**: MEP database and output directory paths are currently fixed. 

2. **Ollama Availability**: The script requires a running Ollama instance with specific models. No retry logic on failure.

3. **Error Handling**: Translation failures return original text without explicit error reporting. Consider enabling logs for debugging.

4. **Context Window**: Context window sizes are conditionally set based on text length but may need tuning for very large debates.

5. **No Caching**: Re-runs perform full translation even if already done.

6. **No Progress Persistence**: Failed runs must restart from the beginning.
