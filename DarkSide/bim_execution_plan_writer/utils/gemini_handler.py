import google.generativeai as genai
import os
import json
from .docx_handler import read_text

def get_gemini_response(message, history, filepath):
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return "Error: API Key not found. Please set GOOGLE_API_KEY or GEMINI_API_KEY environment variable.", []
    
    genai.configure(api_key=api_key)
    
    doc_content = read_text(filepath)
    
    # Construct prompt
    prompt = f"""
    You are an intelligent BIM Execution Plan assistant. Your goal is to help the user complete and improve their BIM Execution Plan (BEP).
    
    CONTEXT:
    The user has uploaded a BEP document. Here is the text content of the document:
    ---
    {doc_content[:15000]} 
    ---
    
    USER MESSAGE:
    {message}
    
    TASK:
    1. Analyze the user's message and the document content.
    2. If the user is answering a question or providing info, identify where it should go in the document.
    3. If the document is missing key info (Point Person, Live Link/ACC Bridge method, Publish Schedule, Delivery Format), and the user hasn't provided it, you should ask about it in your response.
    4. Generate a JSON response with:
       - 'response': A conversational response to the user.
       - 'edits': A list of edits.
    
    EDITS FORMAT:
    - Replace: {{ "type": "replace", "original": "exact string to find", "new": "new string" }}
    - Append: {{ "type": "append", "text": "text to add at the end" }}
    
    Only generate edits if you are confident about what to change. Use 'replace' for filling placeholders.
    
    OUTPUT JSON ONLY.
    """
    
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content(prompt)
        text_resp = response.text
        
        # Clean markdown
        if text_resp.strip().startswith("```json"):
            text_resp = text_resp.strip().split("```json")[1].split("```")[0]
        elif text_resp.strip().startswith("```"):
            text_resp = text_resp.strip().split("```")[1].split("```")[0]
            
        data = json.loads(text_resp)
        return data.get('response', 'Error parsing response'), data.get('edits', [])
        
    except Exception as e:
        return f"Error with AI: {str(e)}", []
