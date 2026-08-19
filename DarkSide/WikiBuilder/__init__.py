"""
WikiBuilder - A minimalist wiki generator for EnneadTab knowledge base.

Features:
- Clean, modern design with earthy color palette
- Responsive layout with sidebar navigation
- Search functionality
- Embedded content for static deployment
- Consistent styling across all pages
"""
try:
    from .wiki_generator import WikiGenerator
except ImportError:
    from wiki_generator import WikiGenerator

import shutil
import os

def generate_wiki(wiki_repo_path, rhino_data_file, revit_data_file):
    """
    Generate the complete wiki website.
    
    Args:
        wiki_repo_path (str): Path to the wiki repository
        rhino_data_file (str): Path to Rhino knowledge data file
        revit_data_file (str): Path to Revit knowledge data file
        
    Returns:
        bool: True if successful, False otherwise
    """
    generator = WikiGenerator(wiki_repo_path, rhino_data_file, revit_data_file)
    result = generator.generate()

    
    return result 


if __name__ == "__main__":
    possible_github_folder = [r"C:\Users\szhang\duck-repo", r"C:\Users\szhang\github"]
    for github_folder in possible_github_folder:
        if os.path.exists(github_folder):
            break
    else:
        raise FileNotFoundError(f"No GitHub folder found in {possible_github_folder}")
    
    generator = WikiGenerator(
        wiki_repo_path=os.path.join(github_folder, "EnneadTabWiki"),
        rhino_data_file=os.path.join(github_folder, "EnneadTab-OS", "Apps", "_rhino", "knowledge_rhino_database.sexyDuck"),
        revit_data_file=os.path.join(github_folder, "EnneadTab-OS", "Apps", "_revit", "knowledge_revit_database.sexyDuck")
    )
    generator.generate()
    