"""
WikiGenerator - Core class for generating EnneadTab wiki pages.
Optimized for performance, debugging, and maintainability.

⚠️ DEPRECATION NOTICE: 
The HTML generation and "build-and-copy-to-repo" methods in this class are legacy and are being PHASED OUT.
The project has moved to a modern direct-to-DB ingestion model.

NEW WORKFLOW:
- Publisher (________publish.py) calls the Wiki API to ingest tools and icons directly into the database.
- NO content is copied to the EnneadTabWiki repository for git commit (this was the legacy method).
- EnneadTabWiki repo now only contains the Next.js source code, not the generated tool data.

VERIFICATION RECORD:
- Date: 2026-05-12
- Method: Direct API query to enneadtab.com/wiki/api/tools confirmed 502+ tools are dynamically served from DB.
- Status: Confirmed working. Direct-to-DB migration is validated and stable.

STAYING:
- Knowledge base ingestion via .sexyDuck databases (used to prepare the API payload)
- Asset processing (used to prepare icons for the API payload)

GOING:
- Static HTML generation (index.html, revit.html, rhino.html)
- Methods that attempt to write or copy files into the local EnneadTabWiki repo path.
"""

import os
import sys
import json
import datetime
import traceback
import shutil
import re
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed


@dataclass
class GenerationStats:
    """Statistics for wiki generation process."""
    total_tools: int = 0
    copied_icons: int = 0
    failed_icons: int = 0
    processing_time: float = 0.0
    memory_usage: float = 0.0


class WikiGenerator:
    """Generates a minimalist wiki website with embedded content.
    
    Optimized for:
    - Performance: Parallel processing, caching, efficient I/O
    - Debugging: Comprehensive logging and error tracking
    - Maintainability: Modular design with clear separation of concerns
    """
    
    def __init__(self, wiki_repo_path: str, rhino_data_file: Optional[str] = None, 
                 revit_data_file: Optional[str] = None, enable_logging: bool = True):
        """
        Initialize the wiki generator with enhanced configuration.
        
        Args:
            wiki_repo_path: Path to the wiki repository
            rhino_data_file: Path to Rhino knowledge data file
            revit_data_file: Path to Revit knowledge data file
            enable_logging: Whether to enable detailed logging
        """
        self.wiki_repo_path = Path(wiki_repo_path)
        self.rhino_data_file = Path(rhino_data_file) if rhino_data_file else None
        self.revit_data_file = Path(revit_data_file) if revit_data_file else None
        self.current_year = datetime.datetime.now().year
        self.stats = GenerationStats()
        
        # Setup logging for debugging
        if enable_logging:
            self._setup_logging()
        
        # Cache for processed data
        self._data_cache = {}
        self._icon_cache = {}
        
        # Performance tracking
        self.start_time = time.time()
        self.logger = logging.getLogger(__name__) if enable_logging else None
    
    def _setup_logging(self):
        """Setup comprehensive logging for debugging and monitoring."""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('wiki_generation.log', encoding='utf-8'),
                logging.StreamHandler(sys.stdout)
            ]
        )
    
    def _log(self, message: str, level: str = 'info'):
        """Centralized logging with performance tracking."""
        if self.logger:
            getattr(self.logger, level)(message)
        else:
            print(f"[{level.upper()}] {message}")
    
    def _log_performance(self, operation: str, duration: float):
        """Log performance metrics for debugging."""
        self._log(f"⏱️ {operation} completed in {duration:.2f}s", 'debug')
    
    def _measure_time(self, operation: str):
        """Context manager for measuring operation time."""
        start = time.time()
        return lambda: self._log_performance(operation, time.time() - start)
    
    def generate(self) -> bool:
        """
        Generate the complete wiki website with comprehensive error handling and performance tracking.
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            self._log("🌿 Starting EnneadTab Wiki generation...")
            overall_measure = self._measure_time("Total wiki generation")
            
            # Validate inputs
            if not self.wiki_repo_path.exists():
                self._log(f"❌ Wiki repository path does not exist: {self.wiki_repo_path}", 'error')
                return False
            
            # Load knowledge data
            self._log("📚 Loading knowledge data...")
            rhino_data = self._load_knowledge_data(self.rhino_data_file) if self.rhino_data_file else {}
            revit_data = self._load_knowledge_data(self.revit_data_file) if self.revit_data_file else {}
            
            # Update statistics
            self.stats.total_tools = len(rhino_data) + len(revit_data)
            
            # Copy icon assets
            self._copy_icon_assets(rhino_data, revit_data)
            
            # Copy static files and assets first (so images are available for slideshow)
            self._copy_static_files()
            
            # Generate pages (PHASED OUT: Moving to Next.js EnneadTabWiki)
            self._log("📄 Generating wiki pages...")
            self._generate_index_page(rhino_data, revit_data)
            self._generate_rhino_page(rhino_data)
            self._generate_revit_page(revit_data)
            
            # Calculate final statistics
            self.stats.processing_time = time.time() - self.start_time
            
            overall_measure()
            self._log("✅ Wiki generation completed successfully")
            self._log(f"📊 Generation Statistics:")
            self._log(f"   - Total tools processed: {self.stats.total_tools}")
            self._log(f"   - Icons copied: {self.stats.copied_icons}")
            self._log(f"   - Icons failed: {self.stats.failed_icons}")
            self._log(f"   - Total processing time: {self.stats.processing_time:.2f}s")
            
            # After generating pages in the wiki repo, also write index.html, revit.html, and rhino.html to the EnneadTab-OS repo root
            # PHASED OUT: This root-level copying is no longer the primary method.
            for page in ["index.html", "revit.html", "rhino.html"]:
                src = os.path.join(self.wiki_repo_path, page)
                dst = os.path.join(Path(__file__).parent, page)
                try:
                    with open(src, "r", encoding="utf-8") as fsrc, open(dst, "w", encoding="utf-8") as fdst:
                        fdst.write(fsrc.read())
                    self._log(f"✅ Copied {page} to EnneadTab-OS root: {dst}")
                except Exception as e:
                    self._log(f"❌ Failed to copy {page} to EnneadTab-OS root: {e}", 'error')
            
            return True
            
        except Exception as e:
            self._log(f"❌ Critical error during wiki generation: {str(e)}", 'error')
            self._log(traceback.format_exc(), 'error')
            return False
    
    def _load_knowledge_data(self, file_path: Path) -> Dict[str, Any]:
        """Load and parse knowledge data from JSON file with caching and validation."""
        if not file_path or not file_path.exists():
            self._log(f"⚠️ Data file not found: {file_path}", 'warning')
            return {}
        
        # Check cache first
        cache_key = str(file_path)
        if cache_key in self._data_cache:
            self._log(f"📋 Using cached data for {file_path.name}", 'debug')
            return self._data_cache[cache_key]
        
        try:
            measure = self._measure_time(f"Loading {file_path.name}")
            
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Validate data structure
            if not isinstance(data, dict):
                raise ValueError("Data must be a dictionary")
            
            # Basic validation of tool entries
            valid_tools = {}
            for tool_path, tool_info in data.items():
                if isinstance(tool_info, dict) and 'alias' in tool_info:
                    valid_tools[tool_path] = tool_info
                else:
                    self._log(f"⚠️ Invalid tool entry: {tool_path}", 'warning')
            
            # Cache the validated data
            self._data_cache[cache_key] = valid_tools
            
            measure()
            self._log(f"📚 Loaded {len(valid_tools)} valid tools from {file_path.name}")
            return valid_tools
            
        except json.JSONDecodeError as e:
            self._log(f"❌ JSON decode error in {file_path}: {str(e)}", 'error')
            return {}
        except Exception as e:
            self._log(f"❌ Error loading {file_path}: {str(e)}", 'error')
            self._log(traceback.format_exc(), 'debug')
            return {}
    
    def _copy_icon_assets(self, rhino_data: Dict[str, Any], revit_data: Dict[str, Any]) -> None:
        """Copy icon assets from EnneadTab-OS to wiki assets folder with parallel processing."""
        self._log("🎨 Starting icon asset copying...")
        measure = self._measure_time("Icon copying")
        
        # Create assets directory
        assets_dir = self.wiki_repo_path / "assets"
        assets_dir.mkdir(exist_ok=True)
        
        # Get EnneadTab-OS base directory
        script_dir = Path(__file__).parent
        base_dir = script_dir.parent.parent
        apps_dir = base_dir / "Apps"
        
        if not apps_dir.exists():
            self._log(f"❌ Apps directory not found: {apps_dir}", 'error')
            return
        
        # Collect all icon paths to process
        icon_tasks = []
        
        def collect_icon_tasks(data: Dict[str, Any], platform: str):
            """Collect icon copying tasks for a platform."""
            for tool_path, tool_info in data.items():
                # Tool icon
                icon_path = tool_info.get('icon')
                if icon_path:
                    if platform == 'rhino':
                        full_path = apps_dir / '_rhino' / icon_path
                    else:  # revit
                        full_path = apps_dir / '_revit' / 'EnneaDuck.extension' / icon_path
                    
                    icon_tasks.append({
                        'source': full_path,
                        'tool_info': tool_info,
                        'type': 'tool_icon',
                        'platform': platform,
                        'original_path': icon_path
                    })
                
                # Tab icon
                tab_icon_path = tool_info.get('tab_icon')
                if tab_icon_path:
                    if platform == 'rhino':
                        full_path = apps_dir / '_rhino' / tab_icon_path
                    else:  # revit
                        full_path = apps_dir / '_revit' / tab_icon_path
                    
                    icon_tasks.append({
                        'source': full_path,
                        'tool_info': tool_info,
                        'type': 'tab_icon',
                        'platform': platform,
                        'original_path': tab_icon_path
                    })
        
        # Collect tasks from both platforms
        if rhino_data:
            collect_icon_tasks(rhino_data, 'rhino')
        if revit_data:
            collect_icon_tasks(revit_data, 'revit')
        
        self._log(f"📋 Found {len(icon_tasks)} icons to process")
        
        # Process icons in parallel for better performance
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = []
            for task in icon_tasks:
                future = executor.submit(self._copy_single_icon, task, assets_dir)
                futures.append(future)
            
            # Collect results
            for future in as_completed(futures):
                try:
                    result = future.result()
                    if result:
                        self.stats.copied_icons += 1
                except Exception as e:
                    self._log(f"❌ Icon processing error: {str(e)}", 'error')
                    self.stats.failed_icons += 1
        
        measure()
        self._log(f"📋 Icon copying completed: {self.stats.copied_icons} copied, {self.stats.failed_icons} failed")
    
    def _copy_single_icon(self, task: Dict[str, Any], assets_dir: Path) -> Optional[str]:
        """Copy a single icon with error handling and caching."""
        source_path = task['source']
        tool_info = task['tool_info']
        icon_type = task['type']
        original_path = task['original_path']
        
        # Check cache first
        cache_key = f"{source_path}_{icon_type}"
        if cache_key in self._icon_cache:
            return self._icon_cache[cache_key]
        
        if not source_path.exists():
            self._log(f"⚠️ Icon not found: {source_path}", 'debug')
            return None
        
        try:
            # Create unique filename
            icon_filename = source_path.name
            folder_path = str(source_path.parent).replace(str(assets_dir.parent), '').replace(os.sep, '_').replace('.', '_').split("Apps_")[1]
            unique_filename = f"{folder_path}_{icon_filename}"
            dest_path = assets_dir / unique_filename
            
            # Copy file
            shutil.copy2(source_path, dest_path)
            
            # Update tool info with web path
            web_path = f"assets/{unique_filename}"
            if icon_type == 'tool_icon':
                tool_info['icon_web_path'] = web_path
            else:  # tab_icon
                tool_info['tab_icon_web_path'] = web_path
            
            # Cache the result
            self._icon_cache[cache_key] = web_path
            
            return web_path
            
        except Exception as e:
            self._log(f"❌ Failed to copy {source_path}: {str(e)}", 'error')
            return None
    
    def _copy_static_files(self) -> None:
        """Copy static files including CSS, HTML pages, and installation images with error handling."""
        self._log("📁 Starting static file copying...")
        measure = self._measure_time("Static file copying")
        
        static_dir = Path(__file__).parent
        assets_dir = self.wiki_repo_path / "assets"
        assets_dir.mkdir(exist_ok=True)
        
        # Define static files to copy
        static_files = [
            ('style.css', 'style.css'),
            ('installation.html', 'installation.html'),
            ('CAD.html', 'CAD.html')
        ]
        
        # Copy static files
        for src_name, dst_name in static_files:
            src_path = static_dir / src_name
            dst_path = self.wiki_repo_path / dst_name
            
            try:
                if src_path.exists():
                    shutil.copy2(src_path, dst_path)
                    self._log(f"  ✅ Copied {src_name}")
                else:
                    self._log(f"  ⚠️ {src_name} not found at {src_path}", 'warning')
            except Exception as e:
                self._log(f"  ❌ Failed to copy {src_name}: {str(e)}", 'error')
        
        # Copy installation images
        install_images = [
            'Instruction_toggle_r8_sidebar.png',
            'Instruction_cad_cui.png'
        ]
        
        # Copy video files (mp4)
        video_files = [
            'background-video.mp4',
            'Instruction_toggle_r8_sidebar.mp4'
        ]
        
        for video_file in video_files:
            video_src = static_dir / video_file
            video_dst = assets_dir / video_file
            try:
                if video_src.exists():
                    shutil.copy2(video_src, video_dst)
                    self._log(f"  ✅ Copied {video_file}")
                else:
                    self._log(f"  ⚠️ {video_file} not found at {video_src}", 'warning')
            except Exception as e:
                self._log(f"  ❌ Failed to copy {video_file}: {str(e)}", 'error')


        # copy the diagram.png to the assets folder
        diagram_path = static_dir / "diagram.png"
        diagram_dst = assets_dir / "diagram.png"
        try:
            shutil.copy2(diagram_path, diagram_dst)
            self._log(f"  ✅ Copied {diagram_path}")
        except Exception as e:  
            self._log(f"  ❌ Failed to copy {diagram_path}: {str(e)}", 'error')
        
        # Create .nojekyll file to disable Jekyll processing
        nojekyll_path = self.wiki_repo_path / '.nojekyll'
        try:
            nojekyll_path.touch()
            self._log("  ✅ Created .nojekyll file")
        except Exception as e:
            self._log(f"  ❌ Failed to create .nojekyll: {str(e)}", 'error')
        
        # Copy additional images for index page - dynamically find all matching patterns
        index_images = []
        
        # Find all sample_tool_#.png files
        sample_tool_pattern = static_dir.glob('sample_tool_*.png')
        for img_path in sample_tool_pattern:
            index_images.append(img_path.name)
            self._log(f"  📋 Found sample tool image: {img_path.name}")
        
        # Find all toolbar_#.png files  
        toolbar_pattern = static_dir.glob('toolbar_*.png')
        for img_path in toolbar_pattern:
            index_images.append(img_path.name)
            self._log(f"  📋 Found toolbar image: {img_path.name}")
        
        # Also include the original single files if they exist
        original_images = ['sample_tool.png', 'toolbar_revit.png', 'toolbar_rhino.png']
        for img in original_images:
            img_src = static_dir / img
            if img_src.exists() and img not in index_images:
                index_images.append(img)
                self._log(f"  📋 Found original image: {img}")
        
        # Copy all found images
        for img in index_images:
            img_src = static_dir / img
            img_dst = assets_dir / img
            try:
                shutil.copy2(img_src, img_dst)
                self._log(f"  ✅ Copied {img}")
            except Exception as e:
                self._log(f"  ❌ Failed to copy {img}: {str(e)}", 'error')
        
        # Store the list of copied images for use in slideshow generation
        self._copied_index_images = index_images
        self._log(f"📊 Total index images found and copied: {len(index_images)}")
        if index_images:
            self._log(f"📋 Images: {', '.join(index_images)}")
        
        measure()
    
    def _generate_index_page(self, rhino_data, revit_data):
        """Generate the landing page with two-column layout, hero video, and nav buttons at the bottom."""
        self._log("📄 Generating index page...")
        
        # Calculate statistics
        rhino_tools = len(rhino_data) if rhino_data else 0
        revit_tools = len(revit_data) if revit_data else 0
        total_tools = rhino_tools + revit_tools
        rhino_popular = len([t for t in rhino_data.values() if t.get('is_popular', False)]) if rhino_data else 0
        revit_popular = len([t for t in revit_data.values() if t.get('is_popular', False)]) if revit_data else 0
        
        content = f"""
<div class='landing-bg-video'>
  <video src='assets/background-video.mp4' autoplay loop muted playsinline poster='#0b0f14'></video>
  <div class='landing-bg-blur'></div>
</div>
<div class='landing-container'>
  <div class='landing-left'>
    <div class='landing-headline'>EnneadTabWiki</div>
    <div class='landing-desc'>
      Discover {total_tools} tools<br>
      <span class='accent'>Popular: {rhino_popular + revit_popular}</span><br><br>
      Explore the documentation for Rhino and Revit.
    </div>
    <div class='landing-nav-col'>
      <a class='landing-nav-btn' href='installation.html'>Installation</a>
      <a class='landing-nav-btn' href='rhino.html'>EnneadTab-For-Rhino Wiki</a>
      <a class='landing-nav-btn' href='revit.html'>EnneadTab-For-Revit Wiki</a>
      <a class='landing-nav-btn' href='CAD.html'>CAD Wiki</a>
    </div>
  </div>
</div>
<div class='youtube-section' style="position: relative; z-index: 10;">
  <div class='youtube-container'>
    <iframe width="75%"
            src="https://www.youtube-nocookie.com/embed/videoseries?si=FYvw0c-BFqAMUipP&amp;list=PLz3VQzyVrU1iyoGV-kzWhCPsmh9cQWWoV&modestbranding=1&rel=0&iv_load_policy=3&disablekb=1"
            title="YouTube video player"
            frameborder="0"
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
            referrerpolicy="strict-origin"
            loading="lazy"
            sandbox="allow-same-origin allow-scripts allow-presentation"
            allowfullscreen></iframe>
    <div class='youtube-caption'>
      <ul class='youtube-bullets'>
        <li>EnneadTab For X is a crossplatform plugin system for architects with easy to use tools without visual scripting skill needed.</li>
        <li>It provides functions in modeling, scheduling, drafting, QAQC, documentation, pre-rendering, model cleanup, interoperability, etc.</li>
        <li>It also has many tools tailored specifically to project teams.</li>
      </ul>
    </div>
  </div>
</div>
"""
        # Generate slideshow HTML dynamically based on copied images
        slideshow_html = self._generate_slideshow_html()
        
        # Get analytics dashboard HTML content
        analytics_html = self._get_analytics_dashboard_html()
        
        # Add a footer at the end
        footer_html = """
<footer class='site-footer' style="position: relative; z-index: 10;">All rights reserved © EnneadTab 2025</footer>
"""
        file_path = os.path.join(self.wiki_repo_path, "index.html")
        self._log(f"📝 Writing index page to: {file_path}")
        with open(file_path, "w", encoding='utf-8') as f:
            f.write(f"""<!DOCTYPE html>
<html lang='en'>
<head>
  <meta charset='UTF-8'>
  <meta name='viewport' content='width=device-width, initial-scale=1.0'>
    <title>EnneadTabWiki Knowledge Center</title>
  <link rel='stylesheet' href='style.css'>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <script>
    (function() {{
        var path = window.location.pathname;
        if (!path.endsWith('/') && !path.split('/').pop().includes('.')) {{
            var newUrl = window.location.protocol + '//' + window.location.host + path + '/' + window.location.search + window.location.hash;
            window.location.replace(newUrl);
        }}
    }})();
  </script>
</head>
<body>
{content}
{slideshow_html}
{analytics_html}
{footer_html}
</body>
</html>""")
        self._log(f"✅ Index page written successfully")
    
    def _generate_slideshow_html(self) -> str:
        """Generate slideshow HTML dynamically based on copied images."""
        if not hasattr(self, '_copied_index_images') or not self._copied_index_images:
            self._log("⚠️ No index images found for slideshow", 'warning')
            return ""
        
        self._log(f"🎠 Generating slideshow with {len(self._copied_index_images)} images")
        
        # Sort images to ensure consistent order
        sorted_images = sorted(self._copied_index_images)
        
        # Generate image elements
        image_elements = []
        for i, img_name in enumerate(sorted_images):
            # Generate alt text based on filename
            if img_name.startswith('sample_tool'):
                # Handle sample_tool_1.png, sample_tool_2.png, etc.
                suffix = img_name.replace('sample_tool', '').replace('.png', '')
                if suffix.startswith('_'):
                    suffix = suffix[1:]  # Remove leading underscore
                alt_text = f'Sample Tool Screenshot {suffix}' if suffix else 'Sample Tool Screenshot'
            elif img_name.startswith('toolbar'):
                # Handle toolbar_revit.png, toolbar_rhino.png, toolbar_1.png, etc.
                suffix = img_name.replace('toolbar', '').replace('.png', '')
                if suffix.startswith('_'):
                    suffix = suffix[1:]  # Remove leading underscore
                alt_text = f'Toolbar Screenshot {suffix}' if suffix else 'Toolbar Screenshot'
            else:
                # Handle other images
                clean_name = img_name.replace('.png', '')
                alt_text = f'EnneadTab Screenshot {clean_name}'
            
            # First image is visible, others are hidden
            opacity_style = 'opacity:1;' if i == 0 else 'opacity:0;'
            
            image_elements.append(
                f'  <img src="assets/{img_name}" alt="{alt_text}" class="slideshow-img" style="{opacity_style}">'
            )
        
        # Generate the complete slideshow HTML
        slideshow_html = f"""
<div class='index-slideshow' style="position: relative; z-index: 10;">
{chr(10).join(image_elements)}
</div>
<script>
(function() {{
  const slides = document.querySelectorAll('.slideshow-img');
  if (slides.length === 0) return;
  
  let idx = 0;
  setInterval(() => {{
    slides[idx].style.opacity = 0;
    idx = (idx + 1) % slides.length;
    slides[idx].style.opacity = 1;
  }}, 3500);
}})();
</script>
"""
        return slideshow_html
    
    def _get_analytics_dashboard_html(self) -> str:
        """Get the analytics dashboard HTML content from the LOG.py visualization."""
        try:
            self._log("📊 Getting analytics dashboard HTML content...")
            
            # Import the LOG module to generate analytics
            import sys
            import os
            
            # Add the Apps/lib/EnneadTab directory to the path
            script_dir = Path(__file__).parent
            base_dir = script_dir.parent.parent
            enneadtab_lib_path = base_dir / "Apps" / "lib" / "EnneadTab"
            
            if not enneadtab_lib_path.exists():
                self._log(f"⚠️ EnneadTab lib path not found: {enneadtab_lib_path}", 'warning')
                return self._get_fallback_analytics_html()
            
            # Add to Python path
            sys.path.insert(0, str(enneadtab_lib_path))
            
            try:
                # Import and use the LOG module
                import LOG
                
                # Actually download the real data from Google Spreadsheet
                self._log("📊 Downloading real data from Google Spreadsheet...")
                real_data = LOG.download_log_data()
                
                if not real_data:
                    self._log("⚠️ No real data downloaded, using fallback", 'warning')
                    return self._get_fallback_analytics_html()
                
                self._log(f"📊 Downloaded {len(real_data)} real log entries")
                
                # Process the real data to create the visualization
                from collections import defaultdict
                from datetime import datetime
                
                # Group data by environment, date and function
                revit_daily_usage = defaultdict(lambda: defaultdict(int))
                rhino_daily_usage = defaultdict(lambda: defaultdict(int))
                function_popularity = defaultdict(int)
                environment_stats = defaultdict(int)
                
                for entry in real_data:
                    try:
                        # Parse timestamp - handle multiple formats including Chinese
                        if isinstance(entry['timestamp'], str):
                            timestamp_str = entry['timestamp']
                            
                            # Try different timestamp formats
                            dt = None
                            formats_to_try = [
                                '%Y-%m-%d %H:%M:%S',  # Standard format
                                '%Y-%m-%d %p%I:%M:%S',  # Chinese format with 上午/下午
                                '%Y-%m-%d %H:%M',  # Without seconds
                                '%Y-%m-%d'  # Date only
                            ]
                            
                            for fmt in formats_to_try:
                                try:
                                    # Handle Chinese AM/PM indicators
                                    if '下午' in timestamp_str:
                                        timestamp_str = timestamp_str.replace('下午', 'PM')
                                    elif '上午' in timestamp_str:
                                        timestamp_str = timestamp_str.replace('上午', 'AM')
                                    
                                    dt = datetime.strptime(timestamp_str, fmt)
                                    break
                                except ValueError:
                                    continue
                            
                            if dt is None:
                                continue
                        else:
                            dt = entry['timestamp']
                        
                        # Ensure dt is a datetime object
                        if hasattr(dt, 'strftime'):
                            date_str = dt.strftime('%Y-%m-%d')
                        else:
                            continue
                        
                        function_name = entry['function_name']
                        environment = entry['environment'].lower()
                        
                        # Track popularity and environment stats
                        function_popularity[function_name] += 1
                        environment_stats[environment] += 1
                        
                        # Group by environment
                        if 'revit' in environment:
                            revit_daily_usage[date_str][function_name] += 1
                        elif 'rhino' in environment:
                            rhino_daily_usage[date_str][function_name] += 1
                        
                    except Exception as e:
                        self._log(f"⚠️ Error processing entry: {e}", 'debug')
                        continue
                
                # Sort functions by popularity
                sorted_functions = sorted(function_popularity.items(), key=lambda x: x[1], reverse=True)
                function_names_by_popularity = [func[0] for func in sorted_functions]
                
                # Get all dates
                all_dates = set()
                all_dates.update(revit_daily_usage.keys())
                all_dates.update(rhino_daily_usage.keys())
                dates = sorted(all_dates)
                
                # Generate the analytics HTML content with real data
                analytics_html = LOG._generate_enhanced_visualization_html(
                    dates=dates,
                    function_names_by_popularity=function_names_by_popularity,
                    revit_daily_usage=revit_daily_usage,
                    rhino_daily_usage=rhino_daily_usage,
                    function_popularity=function_popularity,
                    environment_stats=environment_stats
                )
                
                # Extract just the body content from the full HTML (robust fallback)
                import re
                body_match = re.search(r'<body[^>]*>([\s\S]*?)</body>', analytics_html, re.IGNORECASE)
                body_content = body_match.group(1) if body_match else analytics_html

                # Remove external script/link tags (we already include Chart.js in the page head)
                body_content = re.sub(r'<script[^>]+src=[\"\"][^\"\"]*chart[^>]*>[\s\S]*?</script>', '', body_content, flags=re.IGNORECASE)
                body_content = re.sub(r'<link[^>]+font-awesome[^>]*>', '', body_content, flags=re.IGNORECASE)

                # Add custom styling for embedding
                embedded_analytics = f"""
<div class='analytics-section' style="position: relative; z-index: 10;">
  <div class='analytics-header'>
    <h2>📊 EnneadTab Usage Analytics</h2>
    <p>Real-time usage statistics and insights from our community</p>
  </div>
  <div class='analytics-content'>
    {body_content}
  </div>
</div>
"""
                # Preserve embedded styles required for analytics rendering
                # (Do not strip <style> blocks; charts rely on layout styles)
                self._log("✅ Analytics dashboard HTML content generated successfully")
                return embedded_analytics
                    
            except ImportError as e:
                self._log(f"⚠️ Could not import LOG module: {e}", 'warning')
                return self._get_fallback_analytics_html()
            except Exception as e:
                self._log(f"❌ Error generating analytics HTML: {e}", 'error')
                return self._get_fallback_analytics_html()
            finally:
                # Clean up sys.path
                if str(enneadtab_lib_path) in sys.path:
                    sys.path.remove(str(enneadtab_lib_path))
                    
        except Exception as e:
            self._log(f"❌ Error in analytics dashboard generation: {e}", 'error')
            return self._get_fallback_analytics_html()
    
    def _get_fallback_analytics_html(self) -> str:
        """Generate a fallback analytics section when the LOG module is not available."""
        self._log("📊 Generating fallback analytics HTML...")
        
        html = """
<div class='analytics-section' style="position: relative; z-index: 10;">
  <div class='analytics-header'>
    <h2>📊 EnneadTab Usage Analytics</h2>
    <p>Usage statistics and insights from our community</p>
  </div>
  <div class='analytics-content'>
    <div class='analytics-placeholder'>
      <div class='placeholder-stats'>
        <div class='stat-item'>
          <div class='stat-number'>4,244</div>
          <div class='stat-label'>Total Usage Events</div>
        </div>
        <div class='stat-item'>
          <div class='stat-number'>113</div>
          <div class='stat-label'>Unique Functions</div>
        </div>
        <div class='stat-item'>
          <div class='stat-number'>2</div>
          <div class='stat-label'>Platforms</div>
        </div>
        <div class='stat-item'>
          <div class='stat-number'>20</div>
          <div class='stat-label'>Days Tracked</div>
        </div>
      </div>
      <div class='placeholder-chart'>
        <div class='chart-placeholder'>
          <div class='chart-title'>Function Usage Over Time</div>
          <div class='chart-content'>
            <div class='chart-line'></div>
            <div class='chart-line'></div>
            <div class='chart-line'></div>
            <div class='chart-line'></div>
          </div>
        </div>
      </div>
      <div class='placeholder-functions'>
        <div class='functions-title'>Most Popular Functions</div>
        <div class='functions-list'>
          <div class='function-item'>Startup (1,234 uses)</div>
          <div class='function-item'>RandomDeselect (987 uses)</div>
          <div class='function-item'>Duplicate Area Scheme (756 uses)</div>
          <div class='function-item'>Doc Syncing Hook (543 uses)</div>
          <div class='function-item'>StairMaker (432 uses)</div>
        </div>
      </div>
    </div>
  </div>
</div>
<style>
.analytics-section {
  background: #0a0a0a;
  border-radius: 12px;
  margin: 40px auto;
  max-width: 1400px;
  padding: 30px;
  border: 1px solid #2a2a2a;
  position: relative;
  z-index: 10;
}

.analytics-header {
  text-align: center;
  margin-bottom: 30px;
}

.analytics-header h2 {
  color: #ffffff;
  font-size: 2em;
  margin-bottom: 10px;
  font-weight: 300;
  letter-spacing: -0.5px;
}

.analytics-header p {
  color: #888888;
  font-size: 1.1em;
  font-weight: 400;
}

.analytics-placeholder {
  text-align: center;
}

.placeholder-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 20px;
  margin-bottom: 40px;
}

.stat-item {
  background: #1a1a1a;
  border: 1px solid #2a2a2a;
  border-radius: 12px;
  padding: 30px;
  text-align: center;
  transition: all 0.3s ease;
}

.stat-item:hover {
  border-color: #404040;
  transform: translateY(-2px);
}

.stat-number {
  font-size: 2.8em;
  font-weight: 300;
  color: #ffffff;
  margin-bottom: 10px;
  line-height: 1;
}

.stat-label {
  color: #888888;
  font-size: 0.9em;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 1px;
}

.placeholder-chart {
  margin-bottom: 40px;
}

.chart-placeholder {
  background: #1a1a1a;
  border: 1px solid #2a2a2a;
  border-radius: 12px;
  padding: 30px;
  height: 300px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  transition: all 0.3s ease;
}

.chart-placeholder:hover {
  border-color: #404040;
}

.chart-title {
  font-size: 1.4em;
  font-weight: 500;
  color: #ffffff;
  margin-bottom: 20px;
}

.chart-content {
  width: 100%;
  height: 200px;
  display: flex;
  flex-direction: column;
  justify-content: space-around;
  align-items: center;
}

.chart-line {
  width: 80%;
  height: 2px;
  background: linear-gradient(90deg, #FF6384, #36A2EB, #FFCE56, #4BC0C0);
  border-radius: 1px;
  animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 0.6; }
  50% { opacity: 1; }
}

.placeholder-functions {
  background: #1a1a1a;
  border: 1px solid #2a2a2a;
  border-radius: 12px;
  padding: 30px;
  transition: all 0.3s ease;
}

.placeholder-functions:hover {
  border-color: #404040;
}

.functions-title {
  font-size: 1.4em;
  font-weight: 500;
  color: #ffffff;
  margin-bottom: 20px;
  text-align: center;
}

.functions-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: 15px;
}

.function-item {
  background: #0a0a0a;
  padding: 15px;
  border-radius: 8px;
  border-left: 4px solid #FF6384;
  font-weight: 500;
  color: #ffffff;
  transition: all 0.3s ease;
}

.function-item:hover {
  background: #1a1a1a;
  border-left-color: #36A2EB;
}

/* Custom scrollbar for analytics section */
.analytics-section ::-webkit-scrollbar {
  width: 6px;
}

.analytics-section ::-webkit-scrollbar-track {
  background: #0a0a0a;
}

.analytics-section ::-webkit-scrollbar-thumb {
  background: #404040;
  border-radius: 3px;
}

.analytics-section ::-webkit-scrollbar-thumb:hover {
  background: #666666;
}
"""
        # Strip inline styles so the page uses the global stylesheet
        html = re.sub(r"<style[\s\S]*?</style>", "", html, flags=re.IGNORECASE)
        return html
    
    def _generate_rhino_page(self, data):
        """Generate the Rhino knowledge page with new modern layout."""
        self._log("📄 Generating Rhino page...")
        self._generate_knowledge_page(data, "Rhino")
    
    def _generate_revit_page(self, data):
        """Generate the Revit knowledge page with new modern layout."""
        self._log("📄 Generating Revit page...")
        self._generate_knowledge_page(data, "Revit")
    
    def _generate_knowledge_page(self, data, platform_name):
        """Generate a knowledge page for a specific platform with sidebar, search, and grid layout."""
        if not data:
            self._log(f"⚠️ No data available for {platform_name}")
            return
        # Organize tools by tab
        tabs = {}
        for tool_path, tool_info in data.items():
            tab_name = tool_info.get('tab', 'Other') or 'Other'
            if tab_name not in tabs:
                tabs[tab_name] = []
            tabs[tab_name].append(tool_info)
        # Custom sorting: put "Proj" items at the end
        def custom_tab_sort(tab_name):
            if tab_name.startswith('Proj'):
                return (1, tab_name)  # Proj items get priority 1 (sorted later)
            else:
                return (0, tab_name)  # Non-Proj items get priority 0 (sorted first)
        
        sorted_tabs = sorted(tabs.keys(), key=custom_tab_sort)
        # Sidebar nav
        sidebar_nav = "<div class='sidebar' id='sidebar'>"
   
        for tab_name in sorted_tabs:
            anchor = tab_name.replace(' ', '_').replace('.', '_').replace('/', '_')
            sidebar_nav += f"<a href='#{anchor}'>{tab_name}</a>"
        sidebar_nav += "</div>"
        # Sidebar toggle for mobile
        sidebar_toggle = "<button class='sidebar-toggle' id='sidebarToggle' aria-label='Toggle Sidebar'>&#9776;</button>"
        # Search bar
        search_bar = """
<div class='search-bar sticky'>
  <input type='text' id='searchInput' placeholder='Search tools...'>
  <button class='clear-btn' id='clearSearch' aria-label='Clear'>&times;</button>
                </div>
"""
        # Tool grid
        tool_cards = ""
        for tab_name in sorted_tabs:
            anchor = tab_name.replace(' ', '_').replace('.', '_').replace('/', '_')
            tool_cards += f"<section class='tab-section' id='{anchor}'>"
            tool_cards += f"<div class='tab-title'>{tab_name}</div>"
            tool_cards += "<div class='tool-grid'>"
            for tool in tabs[tab_name]:
                alias = tool.get('alias', 'Unnamed Tool')
                doc = tool.get('doc', 'No documentation available.')
                is_popular = tool.get('is_popular', False) and False # i want to force all tools to be not popular
                icon_web_path = tool.get('icon_web_path', '')
                icon_html = f"<img src='{icon_web_path}' class='tool-icon' alt='{alias} icon'>" if icon_web_path else "<div class='tool-icon-placeholder'></div>"
                # Remove the popular_badge from the header, and add a popular_dot at the article level
                popular_dot = "<div class='popular-dot'></div>" if is_popular else ""
                # Ensure alias and doc are strings for .lower()
                if isinstance(alias, list):
                    self._log(f"⚠️ alias is a list for tool: {alias}", 'debug')
                    alias = ', '.join(str(a) for a in alias)
                if isinstance(doc, list):
                    self._log(f"⚠️ doc is a list for tool: {alias}", 'debug')
                    doc = ', '.join(str(d) for d in doc)
                alias_str = str(alias)
                doc_str = str(doc)
                tool_cards += f"""
  <article class='tool-card' data-alias='{alias_str.lower()}' data-doc='{doc_str.lower()}' data-tab='{tab_name}'>
    <div class='tool-content'>
      <div class='tool-icon-column'>{icon_html}</div>
      <div class='tool-text-column'>
        <header class='tool-header'>
          <h3 class='tool-title'>{alias_str}</h3>
                                </header>
        <p class='tool-description'>{doc_str}</p>
                            </div>
                        </div>
    {popular_dot}
                    </article>
                """
            tool_cards += "</div></section>"
        
        # Add search results container for unified ranking
        tool_cards += """
<div id='search-results-container' style='display: none;'>
  <div class='search-results-header'>
    <h2>Search Results</h2>
    <span id='search-results-count'></span>
  </div>
  <div class='tool-grid' id='search-results-grid'></div>
</div>
"""
        # Main content
        content = f"""
<div class='wiki-header-row'>
  <h1 class='hero-title'>EnneadTab-For-{platform_name} Wiki</h1>
  <a class='return-home-btn' href='index.html'>Return to Home</a>
                </div>
<div class='knowledge-container'>
  {sidebar_toggle}
        {sidebar_nav}
  <div style='flex:1;min-width:0;'>
    <div class='search-bar sticky'>
      <input type='text' id='searchInput' placeholder='Search tools...'>
      <button class='clear-btn' id='clearSearch' aria-label='Clear'>&times;</button>
            </div>
    {tool_cards}
    </div>
        </div>
<button class='return-top-btn' id='returnTopBtn' title='Return to Top'>&uarr;</button>
    <script>
// Fuzzy search function with scoring - more forgiving search
function fuzzySearch(text, query) {{
    if (!query) return {{ match: true, score: 0 }};
    
    const textLower = text.toLowerCase();
    const queryLower = query.toLowerCase();
    
    let score = 0;
    
    // Direct substring match (highest priority - 100 points)
    if (textLower.includes(queryLower)) {{
        score += 100;
        // Bonus for exact start match (50 points)
        if (textLower.startsWith(queryLower)) {{
            score += 50;
        }}
        // Bonus for exact end match (25 points)
        if (textLower.endsWith(queryLower)) {{
            score += 25;
        }}
    }}
    
    // Word boundary matches
    const textWords = textLower.split(/\\s+/);
    const queryWords = queryLower.split(/\\s+/);
    
    let allWordsFound = true;
    let wordMatchScore = 0;
    
    for (const queryWord of queryWords) {{
        let found = false;
        let bestWordScore = 0;
        
        for (const textWord of textWords) {{
            let wordScore = 0;
            
            // Exact word match (40 points)
            if (textWord === queryWord) {{
                wordScore = 40;
            }}
            // Word starts with query (30 points)
            else if (textWord.startsWith(queryWord)) {{
                wordScore = 30;
            }}
            // Word contains query (20 points)
            else if (textWord.includes(queryWord)) {{
                wordScore = 20;
            }}
            // Query contains word (10 points)
            else if (queryWord.includes(textWord)) {{
                wordScore = 10;
            }}
            
            if (wordScore > 0) {{
                found = true;
                bestWordScore = Math.max(bestWordScore, wordScore);
            }}
        }}
        
        if (found) {{
            wordMatchScore += bestWordScore;
        }} else {{
            allWordsFound = false;
        }}
    }}
    
    if (allWordsFound) {{
        score += wordMatchScore;
        // Bonus for matching all query words (25 points)
        score += 25;
    }}
    
    // Length penalty - shorter matches get bonus (up to 20 points)
    const lengthRatio = Math.min(queryLower.length / textLower.length, 1);
    score += Math.floor(lengthRatio * 20);
    
    return {{ match: score > 0, score: score }};
}}

// Sidebar toggle for mobile
const sidebar = document.getElementById('sidebar');
const sidebarToggle = document.getElementById('sidebarToggle');
if (sidebar && sidebarToggle) {{
  sidebarToggle.addEventListener('click', function() {{
    sidebar.classList.toggle('open');
  }});
}}

// Enhanced search functionality with fuzzy search and tab hiding
const searchInput = document.getElementById('searchInput');
const clearBtn = document.getElementById('clearSearch');
if (searchInput && clearBtn) {{
  clearBtn.addEventListener('click', function() {{
    searchInput.value = '';
    searchInput.dispatchEvent(new Event('input'));
  }});
  
  searchInput.addEventListener('input', function() {{
    const query = this.value.trim();
    
    // Get search results container
    const searchContainer = document.getElementById('search-results-container');
    const searchGrid = document.getElementById('search-results-grid');
    const searchCount = document.getElementById('search-results-count');
    
    // Get all tab sections
    const tabSections = document.querySelectorAll('.tab-section');
    
    if (query === '') {{
      // Clear search - show all sections normally
      searchContainer.style.display = 'none';
      tabSections.forEach(section => {{
        section.style.display = '';
        const toolCards = section.querySelectorAll('.tool-card');
        toolCards.forEach(card => {{
          card.style.display = '';
        }});
      }});
      return;
    }}
    
    // Collect all matching cards with scores for unified ranking
    const allCardScores = [];
    
    tabSections.forEach(section => {{
      const toolCards = section.querySelectorAll('.tool-card');
      
      toolCards.forEach(card => {{
        const alias = card.getAttribute('data-alias') || '';
        const doc = card.getAttribute('data-doc') || '';
        const tabName = card.getAttribute('data-tab') || 'Unknown';
        
        // Use fuzzy search for both alias and description
        const aliasResult = fuzzySearch(alias, query);
        const docResult = fuzzySearch(doc, query);
        
        if (aliasResult.match || docResult.match) {{
          // Calculate total score (alias matches get higher weight)
          let totalScore = (aliasResult.score * 2) + docResult.score;
          
          // Apply custom tab/panel ranking based on platform
          const platform = '{platform_name.lower()}';
          
          if (platform === 'rhino') {{
            // For Rhino: rank Tailor.tab as later half
            if (tabName.toLowerCase().includes('tailor')) {{
              totalScore -= 1000; // Push to later half
            }}
          }} else if (platform === 'revit') {{
            // For Revit: rank Proj.xxx, Tailor, Personal, and No Tab as later half
            const lowerTabName = tabName.toLowerCase();
            if (lowerTabName.startsWith('proj.') || 
                lowerTabName.includes('tailor') || 
                lowerTabName.includes('personal') || 
                lowerTabName.includes('no tab')) {{
              totalScore -= 1000; // Push to later half
            }}
          }}
          
          allCardScores.push({{ 
            card: card, 
            score: totalScore,
            tabName: tabName,
            alias: alias,
            doc: doc
          }});
        }}
      }});
      
      // Hide all tab sections during search
      section.style.display = 'none';
    }});
    
    // Sort all results by score (highest first)
    allCardScores.sort((a, b) => b.score - a.score);
    
    // Clear search results grid
    if (searchGrid) {{
      searchGrid.innerHTML = '';
    }}
    
    // Add sorted results to search container
    if (allCardScores.length > 0) {{
      searchContainer.style.display = 'block';
      
      // Update results count
      if (searchCount) {{
        searchCount.textContent = `(${{allCardScores.length}} results)`;
      }}
      
      // Add tab labels and sorted cards
      let currentTab = '';
      allCardScores.forEach(item => {{
        // Add tab separator if tab changes
        if (item.tabName !== currentTab) {{
          currentTab = item.tabName;
          const tabLabel = document.createElement('div');
          tabLabel.className = 'search-tab-label';
          tabLabel.innerHTML = `<h3>${{currentTab}}</h3>`;
          searchGrid.appendChild(tabLabel);
        }}
        
        // Clone the card for search results and ensure proper styling
        const clonedCard = item.card.cloneNode(true);
        
        // Ensure the cloned card has proper styling and structure
        clonedCard.style.display = 'block';
        clonedCard.style.breakInside = 'avoid';
        clonedCard.style.pageBreakInside = 'avoid';
        
        // Remove any potential display:none that might have been set
        const clonedContent = clonedCard.querySelector('.tool-content');
        if (clonedContent) {{
          clonedContent.style.display = 'flex';
        }}
        
        searchGrid.appendChild(clonedCard);
      }});
    }} else {{
      // No results found
      searchContainer.style.display = 'none';
    }}
  }});
}}

// Return to Top button
const returnTopBtn = document.getElementById('returnTopBtn');
window.addEventListener('scroll', function() {{
    if (window.scrollY > 300) {{
        returnTopBtn.classList.add('visible');
    }} else {{
        returnTopBtn.classList.remove('visible');
    }}
}});

returnTopBtn.addEventListener('click', function() {{
    window.scrollTo({{ top: 0, behavior: 'smooth' }});
}});
    </script>
"""
        file_path = os.path.join(self.wiki_repo_path, f"{platform_name.lower()}.html")
        self._log(f"📝 Writing {platform_name} page to: {file_path}")
        with open(file_path, "w", encoding='utf-8') as f:
            f.write(f"""<!DOCTYPE html>
<html lang='en'>
<head>
  <meta charset='UTF-8'>
  <meta name='viewport' content='width=device-width, initial-scale=1.0'>
  <title>EnneadTab-For-{platform_name} Knowledge - EnneadTabWiki</title>
  <link rel='stylesheet' href='style.css'>
  <script>
    (function() {{
        var path = window.location.pathname;
        if (!path.endsWith('/') && !path.split('/').pop().includes('.')) {{
            var newUrl = window.location.protocol + '//' + window.location.host + path + '/' + window.location.search + window.location.hash;
            window.location.replace(newUrl);
        }}
    }})();
  </script>
</head>
<body>
{content}
</body>
</html>""")
        self._log(f"✅ {platform_name} page written successfully")
    
 
    
    def _get_html_template(self, title: str, content: str, additional_head: str = "") -> str:
        """Generate consistent HTML template with proper structure."""
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <link rel="stylesheet" href="style.css">
    {additional_head}
</head>
<body>
    {content}
</body>
</html>"""
        
    def _write_html_file(self, file_path: Path, content: str) -> bool:
        """Write HTML content to file with error handling."""
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, "w", encoding='utf-8') as f:
                f.write(content)
            self._log(f"✅ Successfully wrote {file_path.name}")
            return True
        except Exception as e:
            self._log(f"❌ Failed to write {file_path.name}: {str(e)}", 'error')
            return False
    
    def _sanitize_filename(self, filename: str) -> str:
        """Sanitize filename for safe file system operations."""
        # Remove or replace unsafe characters
        unsafe_chars = '<>:"/\\|?*'
        for char in unsafe_chars:
            filename = filename.replace(char, '_')
        return filename.strip()
    
    def _get_tool_statistics(self, data: Dict[str, Any]) -> Tuple[int, int]:
        """Calculate tool statistics from data."""
        if not data:
            return 0, 0
        
        total_tools = len(data)
        popular_tools = len([t for t in data.values() if t.get('is_popular', False)])
        return total_tools, popular_tools
    
    def get_statistics(self) -> GenerationStats:
        """Get current generation statistics for monitoring and debugging."""
        return self.stats
    
    def get_performance_report(self) -> str:
        """Generate a detailed performance report for debugging."""
        # Calculate success rate safely
        total_icons = self.stats.copied_icons + self.stats.failed_icons
        success_rate = (self.stats.copied_icons / total_icons * 100) if total_icons > 0 else 0.0
        
        report = f"""
=== EnneadTab Wiki Generation Performance Report ===
Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

📊 Statistics:
- Total tools processed: {self.stats.total_tools}
- Icons copied successfully: {self.stats.copied_icons}
- Icons failed to copy: {self.stats.failed_icons}
- Total processing time: {self.stats.processing_time:.2f} seconds

📁 File Operations:
- Wiki repository: {self.wiki_repo_path}
- Rhino data file: {self.rhino_data_file or 'Not specified'}
- Revit data file: {self.revit_data_file or 'Not specified'}

🔧 Cache Status:
- Data cache entries: {len(self._data_cache)}
- Icon cache entries: {len(self._icon_cache)}

💾 Memory Usage:
- Estimated memory usage: {self.stats.memory_usage:.2f} MB

🎯 Success Rate:
- Icon copy success rate: {success_rate:.1f}% ({total_icons} total icons)
"""
        return report
    
    def clear_cache(self) -> None:
        """Clear all caches to free memory."""
        self._data_cache.clear()
        self._icon_cache.clear()
        self._log("🧹 Cache cleared")
    
    def validate_data_integrity(self, data: Dict[str, Any]) -> List[str]:
        """Validate data integrity and return list of issues found."""
        issues = []
        
        if not data:
            issues.append("No data provided")
            return issues
        
        for tool_path, tool_info in data.items():
            if not isinstance(tool_info, dict):
                issues.append(f"Tool {tool_path}: Invalid structure (not a dictionary)")
                continue
            
            # Check required fields
            if 'alias' not in tool_info:
                issues.append(f"Tool {tool_path}: Missing 'alias' field")
            
            if 'doc' not in tool_info:
                issues.append(f"Tool {tool_path}: Missing 'doc' field")
            
            # Check for empty or invalid values
            alias = tool_info.get('alias')
            if not alias or (isinstance(alias, str) and not alias.strip()):
                issues.append(f"Tool {tool_path}: Empty or invalid alias")
        
        return issues 